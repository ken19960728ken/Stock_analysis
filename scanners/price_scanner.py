"""
價格資料撈取 Scanner（重構自 db_market_scanner.py）
從 Yahoo Finance 撈取全市場日K資料
"""
import sys

import pandas as pd
import yfinance as yf

from core.db import save_to_db
from core.local_index import add_index, index_exists
from core.rate_limiter import RateLimiter
from core.scanner_base import BaseScanner
from core.stock_list import get_all_stocks


class PriceScanner(BaseScanner):
    name = "PriceScanner"
    resume_tables = ["daily_price"]

    def __init__(self):
        self.limiter = RateLimiter(source="yahoo")

    def get_targets(self):
        return get_all_stocks()

    def fetch_one(self, target):
        stock_id = target["stock_id"]
        ticker = target["yahoo_symbol"]

        if index_exists("daily_price", stock_id):
            return True

        df = yf.download(ticker, period="3y", progress=False, auto_adjust=False)

        if df.empty:
            return False

        df = df.reset_index()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        df.columns = [c.lower() for c in df.columns]
        df["stock_id"] = stock_id

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.date

        required_cols = ["date", "stock_id", "open", "high", "low", "close", "volume"]
        save_df = df[[c for c in required_cols if c in df.columns]]

        ok = save_to_db(save_df, "daily_price", chunksize=1000)
        if ok:
            add_index("daily_price", stock_id)
        self.limiter.wait()
        return ok


if __name__ == "__main__":
    if "--test" in sys.argv:
        idx = sys.argv.index("--test")
        test_id = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "2330"
        scanner = PriceScanner()
        scanner.get_targets = lambda: [
            {"stock_id": test_id, "yahoo_symbol": f"{test_id}.TW", "name": test_id, "type": "股票"}
        ]
        scanner.resume_tables = []
        scanner.scan()
    else:
        PriceScanner().scan()
