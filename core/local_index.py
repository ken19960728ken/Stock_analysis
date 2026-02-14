"""
本地 SQLite 索引模組
用於記錄哪些 (stock_id, table_name) 已撈取完成，取代遠端 DB 查詢做斷點續傳。
索引檔 scan_index.db 已被 .gitignore 的 *.db 規則覆蓋。
"""
import os
import sqlite3

from core.logger import setup_logger

logger = setup_logger("local_index")

_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scan_index.db")
_conn = None


def _get_conn():
    """取得 SQLite 連線（單例）"""
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(_DB_PATH)
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_index (
                stock_id   TEXT NOT NULL,
                table_name TEXT NOT NULL,
                PRIMARY KEY (stock_id, table_name)
            )
            """
        )
        _conn.commit()
    return _conn


def index_exists(table_name, stock_id):
    """檢查該 (stock_id, table_name) 是否已存在索引"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM scan_index WHERE stock_id = ? AND table_name = ?",
        (stock_id, table_name),
    ).fetchone()
    return row is not None


def add_index(table_name, stock_id):
    """寫入索引，記錄該 (stock_id, table_name) 已完成"""
    conn = _get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO scan_index (stock_id, table_name) VALUES (?, ?)",
        (stock_id, table_name),
    )
    conn.commit()


def all_indexed(table_names, stock_id):
    """檢查所有 table 是否都已索引（用於斷點續傳跳過整支股票）"""
    if not table_names:
        return False
    conn = _get_conn()
    placeholders = ",".join("?" for _ in table_names)
    row = conn.execute(
        f"SELECT COUNT(*) FROM scan_index WHERE stock_id = ? AND table_name IN ({placeholders})",
        (stock_id, *table_names),
    ).fetchone()
    return row[0] == len(table_names)


def init_from_remote():
    """從 Supabase 遠端 DB 讀取各表已有的 stock_id，初始化本地索引"""
    from core.db import get_engine
    from sqlalchemy import text

    engine = get_engine()
    tables = [
        "daily_price",
        "financial_reports",
        "dividend_history",
        "chip_institutional",
        "chip_margin",
        "chip_shareholding",
        "chip_holding_pct",
        "chip_securities_lending",
        "chip_short_sale",
        "month_revenue",
        "stock_per",
        "market_value",
    ]

    conn = _get_conn()
    total = 0

    for table_name in tables:
        try:
            with engine.connect() as db_conn:
                rows = db_conn.execute(
                    text(f"SELECT DISTINCT stock_id FROM {table_name}")
                ).fetchall()

            stock_ids = [r[0] for r in rows]
            for sid in stock_ids:
                conn.execute(
                    "INSERT OR IGNORE INTO scan_index (stock_id, table_name) VALUES (?, ?)",
                    (sid, table_name),
                )
            conn.commit()
            logger.info(f"[init_from_remote] {table_name}: {len(stock_ids)} stocks indexed")
            total += len(stock_ids)

        except Exception as e:
            logger.warning(f"[init_from_remote] {table_name} 跳過: {e}")

    logger.info(f"[init_from_remote] 完成，共索引 {total} 筆記錄")


def close():
    """關閉 SQLite 連線"""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None
