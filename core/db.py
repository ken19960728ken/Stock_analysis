import os

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.logger import setup_logger

logger = setup_logger("db")

load_dotenv()

_engine = None


def get_engine():
    """返回 SQLAlchemy engine 單例"""
    global _engine
    if _engine is None:
        db_url = os.getenv("SUPABASE_URL")
        if not db_url:
            raise RuntimeError("找不到 SUPABASE_URL，請檢查 .env 檔案")
        _engine = create_engine(db_url)
    return _engine


def _pg_insert_ignore(table, conn, keys, data_iter):
    """INSERT ... ON CONFLICT DO NOTHING (PostgreSQL)，自動跳過重複資料"""
    data = [dict(zip(keys, row)) for row in data_iter]
    if not data:
        return
    stmt = pg_insert(table.table).values(data).on_conflict_do_nothing()
    conn.execute(stmt)


def save_to_db(df, table_name, chunksize=500):
    """封裝 to_sql，統一寫入邏輯（自動忽略重複資料）"""
    if df is None or df.empty:
        return False
    try:
        df.to_sql(
            table_name,
            get_engine(),
            if_exists="append",
            index=False,
            method=_pg_insert_ignore,
            chunksize=chunksize,
        )
        return True
    except Exception as e:
        logger.error(f"寫入 {table_name} 失敗: {e}")
        return False


def check_exists(table_name, stock_id, date_col="date"):
    """斷點續傳檢查：該 stock_id 是否已有資料"""
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
