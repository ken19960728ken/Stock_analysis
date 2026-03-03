import os
from urllib.parse import urlparse, urlunparse

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.logger import setup_logger

logger = setup_logger("db")

# 合法資料表白名單（防止 SQL 注入）
VALID_TABLES = frozenset({
    "daily_price", "weekly_price", "monthly_price",
    "financial_reports", "dividend_history", "twstock_code",
    "chip_institutional", "chip_margin", "chip_shareholding",
    "chip_holding_pct", "chip_securities_lending", "chip_short_sale",
    "month_revenue", "stock_per", "market_value",
    "industry_mapping", "scan_progress",
})


def _validate_table_name(table_name: str) -> str:
    """驗證表名是否在白名單中，防止 SQL 注入"""
    if table_name not in VALID_TABLES:
        raise ValueError(f"非法資料表名稱: {table_name!r}")
    return table_name

load_dotenv()

_engine = None


def _ensure_session_mode(db_url: str) -> str:
    """確保使用 Supabase Supavisor session mode (port 5432)。

    Supavisor transaction mode (port 6543) 有連線超時限制，
    不適合批量資料寫入。Session mode (port 5432) 沒有此限制。
    """
    parsed = urlparse(db_url)
    if parsed.port == 6543 and "pooler.supabase.com" in (parsed.hostname or ""):
        fixed = parsed._replace(netloc=parsed.netloc.replace(":6543", ":5432"))
        new_url = urlunparse(fixed)
        logger.info("DB 連線自動切換為 session mode (port 5432)")
        return new_url
    return db_url


def get_engine():
    """返回 SQLAlchemy engine 單例"""
    global _engine
    if _engine is None:
        db_url = os.getenv("SUPABASE_URL")
        if not db_url:
            raise RuntimeError("找不到 SUPABASE_URL，請檢查 .env 檔案")
        db_url = _ensure_session_mode(db_url)
        _engine = create_engine(
            db_url,
            pool_pre_ping=True,        # 每次使用前先 ping，偵測斷線自動重連
            pool_recycle=300,           # 5 分鐘回收連線
            pool_size=2,               # 最多 2 條連線
            max_overflow=0,            # 不建立額外連線
            connect_args={
                "connect_timeout": 30,  # 連線超時 30 秒
                "options": "-c statement_timeout=120000",  # 查詢超時 120 秒
                "keepalives": 1,        # 啟用 TCP keepalive
                "keepalives_idle": 30,  # 30 秒 idle 後發送 keepalive
                "keepalives_interval": 10,  # 每 10 秒重試
                "keepalives_count": 5,  # 5 次失敗後放棄
            },
        )
    return _engine


def _pg_insert_ignore(table, conn, keys, data_iter):
    """INSERT ... ON CONFLICT DO NOTHING (PostgreSQL)，自動跳過重複資料"""
    data = [dict(zip(keys, row)) for row in data_iter]
    if not data:
        return
    stmt = pg_insert(table.table).values(data).on_conflict_do_nothing()
    conn.execute(stmt)


def _is_connection_error(exc: Exception) -> bool:
    """判斷是否為可重試的連線錯誤（SSL 斷線、連線重置等）"""
    msg = str(exc).lower()
    keywords = ("ssl connection", "connection reset", "broken pipe",
                "connection refused", "server closed", "connection timed out")
    return any(kw in msg for kw in keywords)


def _save_chunk(df_chunk, table_name, chunksize):
    """寫入單個批次，連線錯誤時重試一次。"""
    for attempt in range(2):
        try:
            df_chunk.to_sql(
                table_name,
                get_engine(),
                if_exists="append",
                index=False,
                method=_pg_insert_ignore,
                chunksize=chunksize,
            )
            return True
        except Exception as e:
            if attempt == 0 and _is_connection_error(e):
                logger.warning(f"寫入 {table_name} 連線中斷，重置連線池後重試...")
                dispose_engine()
                continue
            logger.error(f"寫入 {table_name} 失敗: {e}")
            return False
    return False


def save_to_db(df, table_name, chunksize=500):
    """封裝 to_sql，統一寫入邏輯（自動忽略重複資料）

    遇到連線斷線時，重置連線池並重試一次。
    """
    if df is None or df.empty:
        return False
    _validate_table_name(table_name)
    return _save_chunk(df, table_name, chunksize)


def check_exists(table_name, stock_id, date_col="date"):
    """斷點續傳檢查：該 stock_id 是否已有資料"""
    _validate_table_name(table_name)
    try:
        sql = text(
            f'SELECT 1 FROM {table_name} WHERE stock_id = :sid LIMIT 1'
        )
        with get_engine().connect() as conn:
            result = conn.execute(sql, {"sid": stock_id}).fetchone()
            return result is not None
    except Exception:
        return False


def ensure_scan_progress_table():
    """確保 scan_progress 表存在"""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS scan_progress (
                    stock_id     TEXT NOT NULL,
                    table_name   TEXT NOT NULL,
                    completed_at TIMESTAMP DEFAULT NOW(),
                    PRIMARY KEY (stock_id, table_name)
                )
            """))
            conn.commit()
    except Exception as e:
        logger.warning(f"建立 scan_progress 表失敗: {e}")


def save_progress(table_name, stock_id):
    """寫入完成記錄到 Supabase scan_progress 表"""
    try:
        with get_engine().connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO scan_progress (stock_id, table_name) "
                    "VALUES (:sid, :tbl) "
                    "ON CONFLICT (stock_id, table_name) DO NOTHING"
                ),
                {"sid": stock_id, "tbl": table_name},
            )
            conn.commit()
    except Exception as e:
        logger.debug(f"寫入 scan_progress 失敗（不影響掃描）: {e}")


def save_progress_batch(table_name, stock_ids):
    """批次寫入完成記錄到 Supabase scan_progress 表（一次 INSERT 多筆）"""
    if not stock_ids:
        return
    try:
        params = [{"sid": sid, "tbl": table_name} for sid in stock_ids]
        with get_engine().connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO scan_progress (stock_id, table_name) "
                    "VALUES (:sid, :tbl) "
                    "ON CONFLICT (stock_id, table_name) DO NOTHING"
                ),
                params,
            )
            conn.commit()
        logger.info(f"批次寫入 scan_progress: {table_name} x {len(stock_ids)} 筆")
    except Exception as e:
        logger.warning(f"批次寫入 scan_progress 失敗: {e}")


def load_progress():
    """從 Supabase scan_progress 表讀取所有完成記錄，回傳 [(stock_id, table_name), ...]"""
    try:
        with get_engine().connect() as conn:
            rows = conn.execute(
                text("SELECT stock_id, table_name FROM scan_progress")
            ).fetchall()
        return rows
    except Exception as e:
        logger.warning(f"讀取 scan_progress 失敗: {e}")
        return []


def dispose_engine():
    """釋放連線"""
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None
