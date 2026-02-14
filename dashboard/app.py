"""
Stock Scanner 監控儀表板 — FastAPI 後端

啟動方式: python main.py --dashboard
"""
import os
import sqlite3
import time

from fastapi import FastAPI
from fastapi.responses import FileResponse

app = FastAPI(title="Stock Scanner Dashboard")

_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scan_index.db")
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# twstock_code 快取（5 分鐘）
_stock_name_cache = {}
_stock_name_cache_ts = 0
_CACHE_TTL = 300

# 追蹤的 12 個表格
TABLE_NAMES = [
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


def _get_sqlite_conn():
    """開獨立的 SQLite 連線（read-only），避免與 scanner 衝突"""
    if not os.path.exists(_DB_PATH):
        return None
    conn = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _get_stock_names():
    """從 Supabase 取得 stock_id → name 對照，快取 5 分鐘"""
    global _stock_name_cache, _stock_name_cache_ts

    if _stock_name_cache and (time.time() - _stock_name_cache_ts < _CACHE_TTL):
        return _stock_name_cache

    try:
        from core.db import get_engine
        from sqlalchemy import text

        engine = get_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT code, name, type FROM twstock_code")
            ).fetchall()
        _stock_name_cache = {r[0]: {"name": r[1], "type": r[2]} for r in rows}
        _stock_name_cache_ts = time.time()
    except Exception:
        # 無法連線時回傳空 dict，不影響其他功能
        if not _stock_name_cache:
            _stock_name_cache = {}
    return _stock_name_cache


@app.get("/")
async def index():
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


@app.get("/api/stats")
async def api_stats():
    """各表格完成統計（圓餅圖資料）"""
    conn = _get_sqlite_conn()
    if conn is None:
        stock_names = _get_stock_names()
        total_stocks = len(stock_names) if stock_names else 0
        return {
            "stats": [
                {"table_name": t, "completed": 0, "remaining": total_stocks, "pct": 0.0}
                for t in TABLE_NAMES
            ],
            "total_stocks": total_stocks,
        }

    try:
        # 每張表的已完成數
        rows = conn.execute(
            "SELECT table_name, COUNT(DISTINCT stock_id) as cnt "
            "FROM scan_index GROUP BY table_name"
        ).fetchall()
        counts = {r["table_name"]: r["cnt"] for r in rows}

        # 用 scan_index 中的最大覆蓋數做分母（= daily_price 完成數，因為它最先跑完）
        total_from_index = conn.execute(
            "SELECT COUNT(DISTINCT stock_id) FROM scan_index"
        ).fetchone()[0] or 0
    finally:
        conn.close()

    # 取 twstock_code 數量與 scan_index 最大覆蓋數的較大值
    stock_names = _get_stock_names()
    total_stocks = max(len(stock_names), total_from_index) if stock_names else total_from_index

    stats = []
    for t in TABLE_NAMES:
        completed = counts.get(t, 0)
        remaining = max(0, total_stocks - completed)
        pct = round(completed / total_stocks * 100, 1) if total_stocks > 0 else 0.0
        stats.append(
            {"table_name": t, "completed": completed, "remaining": remaining, "pct": pct}
        )

    return {"stats": stats, "total_stocks": total_stocks}


@app.get("/api/stocks")
async def api_stocks():
    """商品完成矩陣"""
    stock_names = _get_stock_names()

    conn = _get_sqlite_conn()
    indexed = {}
    if conn is not None:
        try:
            rows = conn.execute("SELECT stock_id, table_name FROM scan_index").fetchall()
            for r in rows:
                sid = r["stock_id"]
                if sid not in indexed:
                    indexed[sid] = set()
                indexed[sid].add(r["table_name"])
        finally:
            conn.close()

    # 合併：stock_names 為底，加上 indexed 中有但 stock_names 沒有的
    all_ids = set(stock_names.keys()) | set(indexed.keys())

    stocks = []
    for sid in sorted(all_ids):
        info = stock_names.get(sid, {})
        tables = {t: (t in indexed.get(sid, set())) for t in TABLE_NAMES}
        completed = sum(1 for v in tables.values() if v)
        stocks.append(
            {
                "stock_id": sid,
                "name": info.get("name", ""),
                "type": info.get("type", ""),
                "tables": tables,
                "completed": completed,
                "total": len(TABLE_NAMES),
            }
        )

    return {
        "stocks": stocks,
        "table_names": TABLE_NAMES,
        "total_stocks": len(stocks),
    }


@app.get("/api/failures")
async def api_failures():
    """失敗記錄"""
    stock_names = _get_stock_names()

    conn = _get_sqlite_conn()
    if conn is None:
        return {"failures": [], "total": 0}

    try:
        rows = conn.execute(
            "SELECT stock_id, table_name, error_msg, failed_at "
            "FROM scan_failures ORDER BY failed_at DESC"
        ).fetchall()
    finally:
        conn.close()

    failures = []
    for r in rows:
        sid = r["stock_id"]
        info = stock_names.get(sid, {})
        failures.append(
            {
                "stock_id": sid,
                "name": info.get("name", ""),
                "table_name": r["table_name"],
                "error_msg": r["error_msg"],
                "failed_at": r["failed_at"],
            }
        )

    return {"failures": failures, "total": len(failures)}
