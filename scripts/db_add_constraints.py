"""
為所有資料表新增 Unique Constraint（冪等腳本，可重複執行）

用途：
    uv run python scripts/db_add_constraints.py

此腳本確保所有表都有正確的唯一約束，讓 ON CONFLICT DO NOTHING 生效。
若約束已存在則自動跳過。
"""

import os
import sys
from pathlib import Path

# 確保能 import core/
ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import psycopg2
from urllib.parse import urlparse
from dotenv import load_dotenv

from core.logger import setup_logger

logger = setup_logger("db_constraints")

# 各表的唯一約束定義
CONSTRAINTS = [
    ("daily_price", "uq_daily_price", "stock_id, date"),
    ("weekly_price", "uq_weekly_price", "stock_id, date"),
    ("monthly_price", "uq_monthly_price", "stock_id, date"),
    ("chip_institutional", "uq_chip_institutional", "stock_id, date"),
    ("chip_margin", "uq_chip_margin", "stock_id, date"),
    ("chip_shareholding", "uq_chip_shareholding", "stock_id, date"),
    ("chip_holding_pct", "uq_chip_holding_pct",
     'stock_id, date, "HoldingSharesLevel"'),
    ("chip_securities_lending", "uq_chip_securities_lending",
     "stock_id, date, transaction_type"),
    ("chip_short_sale", "uq_chip_short_sale", "stock_id, date"),
    ("stock_per", "uq_stock_per", "stock_id, date"),
    ("market_value", "uq_market_value", "stock_id, date"),
    ("month_revenue", "uq_month_revenue", "stock_id, date, country"),
    ("financial_reports", "uq_financial_reports", "stock_id, date, type"),
    ("dividend_history", "uq_dividend_history", "stock_id, date, dividend"),
    ("industry_classification", "uq_industry_classification", "stock_id"),
    ("recommendation_history", "uq_recommendation_history", "report_date, stock_id"),
]


def main():
    load_dotenv(os.path.join(ROOT, ".env"))
    db_url = os.getenv("SUPABASE_URL")
    if not db_url:
        logger.error("找不到 SUPABASE_URL")
        return

    parsed = urlparse(db_url)
    # 強制使用 session mode (port 5432)
    port = 5432 if parsed.port == 6543 else (parsed.port or 5432)

    conn = psycopg2.connect(
        host=parsed.hostname, port=port, dbname=parsed.path.lstrip("/"),
        user=parsed.username, password=parsed.password,
        connect_timeout=30
    )
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SET statement_timeout = '1800000'")  # 30 分鐘

    success = 0
    skipped = 0
    failed = 0

    for table, cname, key_cols in CONSTRAINTS:
        # 檢查約束或索引是否已存在
        cur.execute(
            "SELECT 1 FROM pg_indexes WHERE indexname = %s", (cname,)
        )
        if cur.fetchone():
            logger.info(f"[skip] {cname} 已存在")
            skipped += 1
            continue

        # 也檢查 idx_ 前綴版本
        idx_name = f"idx_{cname}"
        cur.execute(
            "SELECT 1 FROM pg_indexes WHERE indexname = %s", (idx_name,)
        )
        if cur.fetchone():
            logger.info(f"[skip] {idx_name} 已存在")
            skipped += 1
            continue

        try:
            logger.info(f"Creating unique index on {table} ({key_cols})...")
            cur.execute(
                f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "
                f"{idx_name} ON {table} ({key_cols})"
            )
            success += 1
            logger.info(f"[ok] {idx_name}")
        except Exception as e:
            failed += 1
            logger.error(f"[fail] {table}: {e}")

    cur.close()
    conn.close()

    logger.info(
        f"完成: {success} 新增, {skipped} 已存在, {failed} 失敗"
    )


if __name__ == "__main__":
    main()
