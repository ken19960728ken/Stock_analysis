"""
估值面資料撈取 Scanner
撈取 3 個 FinMind 資料集：月營收、PER/PBR/殖利率、市值
"""
import sys

import pandas as pd

from core.db import save_to_db
from core.finmind_client import get_fm_loader
from core.local_index import add_index, index_exists
from core.logger import setup_logger
from core.rate_limiter import RateLimiter
from core.scanner_base import BaseScanner

logger = setup_logger("valuation_scanner")

# 估值面資料集定義：(DataLoader 方法名, DB 表名, 說明)
VALUATION_DATASETS = [
    ("taiwan_stock_month_revenue", "month_revenue", "月營收"),
    ("taiwan_stock_per_pbr", "stock_per", "本益比/股價淨值比/殖利率"),
    ("taiwan_stock_market_value", "market_value", "市值"),
]

START_DATE = "2020-01-01"


class ValuationScanner(BaseScanner):
    name = "ValuationScanner"
    resume_tables = [t[1] for t in VALUATION_DATASETS]

    def __init__(self):
        self.fm_loader = get_fm_loader()
        self.limiter = RateLimiter(source="finmind")

    def fetch_one(self, target):
        stock_id = self._get_stock_id(target)
        any_success = False

        for method_name, table_name, label in VALUATION_DATASETS:
            if index_exists(table_name, stock_id):
                continue

            try:
                fetch_fn = getattr(self.fm_loader, method_name)

                def _call(fn=fetch_fn, sid=stock_id):
                    return fn(stock_id=sid, start_date=START_DATE)

                df = self.limiter.call_with_retry(_call)

                if df is not None and not df.empty:
                    if "date" in df.columns:
                        df["date"] = pd.to_datetime(df["date"]).dt.date
                    if save_to_db(df, table_name):
                        add_index(table_name, stock_id)
                        any_success = True

            except Exception as e:
                logger.error(f"[{stock_id}] {label} 失敗: {e}")

            self.limiter.wait()

        return any_success


if __name__ == "__main__":
    if "--test" in sys.argv:
        idx = sys.argv.index("--test")
        test_id = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "2330"
        scanner = ValuationScanner()
        scanner.get_targets = lambda: [test_id]
        scanner.resume_tables = []
        scanner.scan()
    else:
        ValuationScanner().scan()
