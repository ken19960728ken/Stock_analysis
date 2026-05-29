import json
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
    "industry_mapping", "industry_classification", "scan_progress",
    "recommendation_history",  # 選股推薦追蹤
    "scanner_run_log",         # Scanner 執行日誌
    "day_trading",              # 當日沖銷
    "dividend_result",          # 除息結果
    "total_return_index",       # 含息報酬指數
    "stock_delisting",          # 下市櫃
    "securities_trader_info",   # 券商資訊（靜態）
    "chip_broker",              # 券商分點買賣（Sponsor）
    "chip_gov_bank",            # 官股行庫買賣（Sponsor）
    "paper_portfolio",          # Paper Trading 持倉
    "paper_trades",             # Paper Trading 交易記錄
    "paper_daily_pnl",          # Paper Trading 每日損益
    "strategy_tournament_results",  # 策略淘汰賽結果
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
        pool_size = int(os.environ.get("DB_POOL_SIZE", "5"))
        pool_overflow = int(os.environ.get("DB_POOL_OVERFLOW", "3"))
        stmt_timeout = int(os.environ.get("DB_STATEMENT_TIMEOUT", "120000"))
        _engine = create_engine(
            db_url,
            pool_pre_ping=True,        # 每次使用前先 ping，偵測斷線自動重連
            pool_recycle=300,           # 5 分鐘回收連線
            pool_size=pool_size,
            max_overflow=pool_overflow,
            connect_args={
                "connect_timeout": 30,  # 連線超時 30 秒
                "options": f"-c statement_timeout={stmt_timeout}",  # 查詢超時（毫秒）
                "keepalives": 1,        # 啟用 TCP keepalive
                "keepalives_idle": 30,  # 30 秒 idle 後發送 keepalive
                "keepalives_interval": 10,  # 每 10 秒重試
                "keepalives_count": 5,  # 5 次失敗後放棄
            },
        )
    return _engine


def safe_read_sql(sql, params=None, timeout_ms=None):
    """安全的 read_sql 包裝：使用 with connect() 確保連線自動歸還，
    避免 pd.read_sql(sql, engine) 在 SQLAlchemy 2.x 下產生 idle in transaction 殭屍連線。

    支援兩種參數格式：
    - %(param)s  — psycopg2 原生格式，傳入原始字串
    - :param     — SQLAlchemy text() 格式，已由呼叫端包裝

    timeout_ms: 可選，針對此查詢設定 statement_timeout（毫秒），
                用 SET LOCAL 覆蓋 Supabase 伺服器端預設值。
    """
    with get_engine().connect() as conn:
        if timeout_ms is not None:
            conn.execute(text(f"SET statement_timeout = {int(timeout_ms)}"))
        # 已經是 TextClause 就直接用；字串含 %(...)s 是 psycopg2 格式，不能用 text() 包裝
        if isinstance(sql, str) and "%(" not in sql:
            sql = text(sql)
        df = pd.read_sql(sql, conn, params=params)
    return df


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
    import time as _time
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
                _time.sleep(1)
                continue
            logger.error(f"寫入 {table_name} 失敗: {e}")
            return False
    return False


def _auto_serialize_json_columns(df):
    """自動將 DataFrame 中的 dict/list 欄位序列化為 JSON 字串。

    psycopg2 無法直接處理 Python dict/list → PostgreSQL JSONB，
    必須先轉為 JSON 字串，PostgreSQL 會自動將 TEXT 轉為 JSONB。
    在 save_to_db 統一處理，避免每個呼叫端都要記得 json.dumps()。
    """
    df = df.copy()
    for col in df.columns:
        sample = df[col].dropna().head(1)
        if not sample.empty and isinstance(sample.iloc[0], (dict, list)):
            df[col] = df[col].apply(
                lambda x: json.dumps(x, ensure_ascii=False, default=str)
                if isinstance(x, (dict, list)) else x
            )
    return df


# 不需要過濾權證的表（靜態資料、無 stock_id、或本身就是全市場資料）
_NO_WARRANT_FILTER_TABLES = frozenset({
    "twstock_code", "industry_mapping", "industry_classification",
    "recommendation_history", "scanner_run_log",
    "total_return_index", "stock_delisting", "securities_trader_info",
    "paper_portfolio", "paper_trades", "paper_daily_pnl",
    "strategy_tournament_results",
})


def _filter_warrants(df, table_name):
    """過濾權證資料（stock_id >= 6 碼）。

    權證代碼為 6 碼（如 030000），一般股票/ETF 為 4-5 碼。
    除非特定表不需要過濾，否則自動排除權證以節省 DB 空間和 IO。
    """
    if table_name in _NO_WARRANT_FILTER_TABLES:
        return df
    if "stock_id" not in df.columns:
        return df
    before = len(df)
    df = df[df["stock_id"].astype(str).str.len() < 6]
    filtered = before - len(df)
    if filtered > 0:
        logger.debug(f"[{table_name}] 過濾 {filtered} 筆權證資料")
    return df


_table_columns_cache: dict[str, list[str]] = {}


def _get_table_columns(table_name: str) -> list[str] | None:
    """查詢 DB 表的實際欄位名稱（快取結果）。"""
    if table_name in _table_columns_cache:
        return _table_columns_cache[table_name]
    try:
        sql = text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :tbl"
        )
        with get_engine().connect() as conn:
            rows = conn.execute(sql, {"tbl": table_name}).fetchall()
        if rows:
            cols = [r[0] for r in rows]
            _table_columns_cache[table_name] = cols
            return cols
    except Exception as e:
        logger.debug(f"查詢 {table_name} 欄位失敗: {e}")
    return None


def _filter_unknown_columns(df, table_name):
    """移除 DataFrame 中 DB 表不存在的欄位，避免 API schema 變動導致寫入失敗。"""
    db_cols = _get_table_columns(table_name)
    if db_cols is None:
        return df
    extra = [c for c in df.columns if c not in db_cols]
    if extra:
        logger.info(f"[{table_name}] 移除 API 多餘欄位: {extra}")
        df = df.drop(columns=extra)
    return df


def save_to_db(df, table_name, chunksize=500):
    """封裝 to_sql，統一寫入邏輯（自動忽略重複資料）

    - 自動過濾權證資料（stock_id >= 6 碼），避免寫入不必要的資料。
    - 自動移除 DB 表不存在的欄位（防止 API schema 變動導致寫入失敗）。
    - 自動將 dict/list 欄位序列化為 JSON 字串（防止 psycopg2 JSONB 寫入錯誤）
    - 遇到連線斷線時，重置連線池並重試一次。
    """
    if df is None or df.empty:
        return False
    _validate_table_name(table_name)
    df = _filter_warrants(df, table_name)
    if df.empty:
        return False
    df = _filter_unknown_columns(df, table_name)
    if df.empty:
        return False
    df = _auto_serialize_json_columns(df)
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
