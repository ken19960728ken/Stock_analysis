"""
一次性補抓腳本：補齊 2026/2/23~3/13 缺漏資料
1. stock_per + market_value（FinMind 批量查詢）
2. daily_price 缺漏日期（via DailyUpdater）
3. chip 缺漏日期（via DailyUpdater）
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from core.db import save_to_db
from core.finmind_client import get_fm_loader
from core.logger import setup_logger
from core.rate_limiter import RateLimiter
from scanners.daily_updater import DailyUpdater

logger = setup_logger("backfill")

# 所有需要補抓的交易日
ALL_DATES = [
    "2026-02-23", "2026-02-24", "2026-02-25", "2026-02-26",
    "2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05",
    "2026-03-06", "2026-03-09", "2026-03-10", "2026-03-11",
    "2026-03-12", "2026-03-13",
]


def backfill_valuation():
    """補抓 stock_per + market_value（批量查詢，不帶 stock_id）"""
    print("=" * 60)
    print("補抓 stock_per + market_value")
    print("=" * 60)

    fm = get_fm_loader()
    limiter = RateLimiter(source="finmind")

    datasets = [
        ("taiwan_stock_per_pbr", "stock_per", "PER/PBR"),
        ("taiwan_stock_market_value", "market_value", "市值"),
    ]

    for method_name, table_name, label in datasets:
        print(f"\n--- {label} ({table_name}) ---")
        total_rows = 0

        for date_str in ALL_DATES:
            fetch_fn = getattr(fm, method_name)

            def _call(fn=fetch_fn, d=date_str):
                return fn(start_date=d, end_date=d)

            try:
                df = limiter.call_with_retry(_call)
            except Exception as e:
                print(f"  {date_str} 查詢失敗: {e}")
                limiter.wait()
                continue

            if df is None or df.empty:
                print(f"  {date_str} 無資料（非交易日或尚未公布）")
                limiter.wait()
                continue

            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"]).dt.date

            ok = save_to_db(df, table_name)
            n = len(df) if ok else 0
            total_rows += n
            print(f"  {date_str} 寫入 {n} 筆")
            limiter.wait()

        print(f"  [{label}] 共寫入 {total_rows} 筆")


def backfill_daily_updater():
    """用 DailyUpdater 補抓 price + chip 缺漏"""
    print("\n" + "=" * 60)
    print("補抓 daily_price + chip（DailyUpdater）")
    print("=" * 60)

    updater = DailyUpdater()

    for date_str in ALL_DATES:
        print(f"\n--- {date_str} ---")
        updater.run(target_date=date_str)


def main():
    print("開始補抓缺漏資料...\n")

    # 🔴 優先級 1: stock_per + market_value
    backfill_valuation()

    # 🔴🟡 優先級 2+3: daily_price + chip
    backfill_daily_updater()

    print("\n" + "=" * 60)
    print("補抓完成！請重新執行 db_integrity_check.py 驗證。")
    print("=" * 60)


if __name__ == "__main__":
    main()
