import os

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

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


def save_to_db(df, table_name, chunksize=500):
    """封裝 to_sql，統一寫入邏輯"""
    if df is None or df.empty:
        return False
    try:
        df.to_sql(
            table_name,
            get_engine(),
            if_exists="append",
            index=False,
            method="multi",
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


def dispose_engine():
    """釋放連線"""
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None
