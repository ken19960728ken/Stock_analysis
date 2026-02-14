"""
本地 SQLite 索引模組
用於記錄哪些 (stock_id, table_name) 已撈取完成，取代遠端 DB 查詢做斷點續傳。
索引檔 scan_index.db 已被 .gitignore 的 *.db 規則覆蓋。
"""
import os
import sqlite3
from datetime import datetime

from core.logger import setup_logger

logger = setup_logger("local_index")

_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scan_index.db")
_conn = None


def _get_conn():
    """取得 SQLite 連線（單例），首次建立時自動從遠端同步"""
    global _conn
    if _conn is None:
        is_new = not os.path.exists(_DB_PATH)
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
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scan_failures (
                stock_id   TEXT NOT NULL,
                table_name TEXT NOT NULL,
                error_msg  TEXT,
                failed_at  TEXT NOT NULL,
                PRIMARY KEY (stock_id, table_name)
            )
            """
        )
        _conn.commit()

        # 新建本地 DB 時自動從遠端同步
        if is_new:
            logger.info("本地索引不存在，自動從遠端同步...")
            try:
                init_from_remote()
            except Exception as e:
                logger.warning(f"自動同步失敗（不影響執行）: {e}")
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
    """寫入索引，記錄該 (stock_id, table_name) 已完成（本地 + 遠端）"""
    conn = _get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO scan_index (stock_id, table_name) VALUES (?, ?)",
        (stock_id, table_name),
    )
    conn.commit()

    # 同步寫入 Supabase（非阻塞，失敗不影響掃描）
    try:
        from core.db import save_progress
        save_progress(table_name, stock_id)
    except Exception:
        pass


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
    """從 Supabase 初始化本地索引（優先用 scan_progress 表，fallback 掃描資料表）"""
    from core.db import ensure_scan_progress_table, load_progress

    # 1. 確保 scan_progress 表存在
    ensure_scan_progress_table()

    # 2. 優先從 scan_progress 表同步（快速，一次查詢）
    rows = load_progress()
    if rows:
        conn = _get_conn()
        for stock_id, table_name in rows:
            conn.execute(
                "INSERT OR IGNORE INTO scan_index (stock_id, table_name) VALUES (?, ?)",
                (stock_id, table_name),
            )
        conn.commit()
        logger.info(f"[init_from_remote] 從 scan_progress 同步 {len(rows)} 筆記錄")
        return

    # 3. Fallback：掃描各資料表的 DISTINCT stock_id（首次使用時）
    logger.info("[init_from_remote] scan_progress 為空，改為掃描各資料表...")
    _init_from_data_tables()


def _init_from_data_tables():
    """從各資料表的 DISTINCT stock_id 初始化本地索引（首次用）"""
    from core.db import get_engine, save_progress_batch
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

            # 批次回寫 scan_progress 表（一次 INSERT 而非逐筆）
            save_progress_batch(table_name, stock_ids)

            logger.info(f"[init_from_remote] {table_name}: {len(stock_ids)} stocks indexed")
            total += len(stock_ids)

        except Exception as e:
            logger.warning(f"[init_from_remote] {table_name} 跳過: {e}")

    logger.info(f"[init_from_remote] 完成，共索引 {total} 筆記錄")


def add_failure(table_name, stock_id, error_msg=""):
    """記錄失敗的 (stock_id, table_name)，INSERT OR REPLACE"""
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO scan_failures (stock_id, table_name, error_msg, failed_at) VALUES (?, ?, ?, ?)",
        (stock_id, table_name, str(error_msg), datetime.now().isoformat()),
    )
    conn.commit()


def failure_exists(table_name, stock_id):
    """檢查該 (stock_id, table_name) 是否有失敗記錄"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM scan_failures WHERE stock_id = ? AND table_name = ?",
        (stock_id, table_name),
    ).fetchone()
    return row is not None


def clear_failures(table_name=None):
    """清除失敗記錄（全部或指定 dataset）"""
    conn = _get_conn()
    if table_name:
        conn.execute(
            "DELETE FROM scan_failures WHERE table_name = ?", (table_name,)
        )
    else:
        conn.execute("DELETE FROM scan_failures")
    conn.commit()


def get_failure_summary():
    """回傳失敗統計 [(table_name, count), ...]"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT table_name, COUNT(*) FROM scan_failures GROUP BY table_name ORDER BY COUNT(*) DESC"
    ).fetchall()
    return rows


def close():
    """關閉 SQLite 連線"""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None
