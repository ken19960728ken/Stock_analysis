"""
籌碼面資料撈取 Scanner
撈取 6 個 FinMind 資料集：三大法人、融資融券、股權分散、持股比例、借券、借券賣出餘額
"""
import sys

import pandas as pd

from core.db import save_to_db
from core.finmind_client import get_fm_loader, get_fm_token
from core.logger import setup_logger
from core.rate_limiter import RateLimiter
from core.scanner_base import BaseScanner

logger = setup_logger("chip_scanner")

# 籌碼面資料集定義：(DataLoader 方法名, DB 表名, 說明)
CHIP_DATASETS = [
    ("taiwan_stock_institutional_investors", "chip_institutional", "三大法人買賣超"),
    ("taiwan_stock_margin_purchase_short_sale", "chip_margin", "融資融券"),
    ("taiwan_stock_shareholding", "chip_shareholding", "股權分散表"),
    ("taiwan_stock_holding_shares_per", "chip_holding_pct", "持股比例"),
    ("taiwan_stock_securities_lending", "chip_securities_lending", "借券資料"),
    ("taiwan_stock_daily_short_sale_balances", "chip_short_sale", "借券賣出餘額"),
]

START_DATE = "2020-01-01"


class ChipScanner(BaseScanner):
    name = "ChipScanner"
    resume_table = "chip_institutional"  # 用第一個表檢查斷點

    def __init__(self):
        self.fm_loader = get_fm_loader()
        self.fm_token = get_fm_token()
        self.limiter = RateLimiter(source="finmind")

    def fetch_one(self, target):
        stock_id = self._get_stock_id(target)
        any_success = False

        for method_name, table_name, label in CHIP_DATASETS:
            try:
                fetch_fn = getattr(self.fm_loader, method_name)

                def _call(fn=fetch_fn, sid=stock_id):
                    return fn(stock_id=sid, start_date=START_DATE, token=self.fm_token)

                df = self.limiter.call_with_retry(_call)

                if df is not None and not df.empty:
                    if "date" in df.columns:
                        df["date"] = pd.to_datetime(df["date"]).dt.date
                    if save_to_db(df, table_name):
                        any_success = True

            except Exception as e:
                logger.error(f"[{stock_id}] {label} 失敗: {e}")

            self.limiter.wait()

        return any_success


if __name__ == "__main__":
    if "--test" in sys.argv:
        idx = sys.argv.index("--test")
        test_id = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "2330"
        scanner = ChipScanner()
        scanner.get_targets = lambda: [test_id]
        scanner.resume_table = None
        scanner.scan()
    else:
        ChipScanner().scan()
