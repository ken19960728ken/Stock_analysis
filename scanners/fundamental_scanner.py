"""
基本面資料撈取 Scanner（合併自 fundamental_scanner.py + get_financial_report.py）
撈取：財務報表（損益表 + 資產負債表）、股利、季報 EPS
"""
import sys

import pandas as pd
import yfinance as yf

from core.db import save_to_db
from core.finmind_client import get_fm_loader, get_fm_token
from core.rate_limiter import RateLimiter
from core.scanner_base import BaseScanner

FOCUS_METRICS = [
    "Revenue",
    "GrossProfit",
    "OperatingIncome",
    "NetIncome",
    "EarningsPerShare",
    "TotalAssets",
    "TotalLiabilities",
    "TotalEquity",
    "CashFlowsFromOperatingActivities",
]

START_DATE = "2020-01-01"


class FundamentalScanner(BaseScanner):
    name = "FundamentalScanner"
    resume_table = "financial_reports"

    def __init__(self):
        self.fm_loader = get_fm_loader()
        self.fm_token = get_fm_token()
        self.limiter = RateLimiter(source="finmind")
        self.yahoo_limiter = RateLimiter(source="yahoo")

    def fetch_one(self, target):
        stock_id = self._get_stock_id(target)
        any_success = False

        # 1. 財務報表（損益表 + 資產負債表）
        df_fin = self._fetch_financial_statements(stock_id)
        if df_fin is not None:
            if save_to_db(df_fin, "financial_reports"):
                any_success = True
        self.limiter.wait()

        # 2. 股利（Yahoo Finance）
        df_div = self._fetch_dividends(stock_id)
        if df_div is not None:
            if save_to_db(df_div, "dividend_history"):
                any_success = True
        self.yahoo_limiter.wait()

        return any_success

    def _fetch_financial_statements(self, stock_id):
        """抓取損益表 + 資產負債表，篩選關鍵指標"""
        try:
            def _call_income():
                return self.fm_loader.taiwan_stock_financial_statement(
                    stock_id=stock_id, start_date=START_DATE, token=self.fm_token,
                )

            def _call_balance():
                return self.fm_loader.taiwan_stock_balance_sheet(
                    stock_id=stock_id, start_date=START_DATE, token=self.fm_token,
                )

            df_income = self.limiter.call_with_retry(_call_income)
            self.limiter.wait()
            df_balance = self.limiter.call_with_retry(_call_balance)

            df_list = []
            if df_income is not None and not df_income.empty:
                df_list.append(df_income)
            if df_balance is not None and not df_balance.empty:
                df_list.append(df_balance)

            if not df_list:
                return None

            df_all = pd.concat(df_list, ignore_index=True)
            df_all["type"] = df_all["type"].astype(str).str.strip()
            df_filtered = df_all[df_all["type"].isin(FOCUS_METRICS)].copy()

            if df_filtered.empty:
                return None

            df_filtered = df_filtered[["date", "stock_id", "type", "value"]]
            df_filtered["date"] = pd.to_datetime(df_filtered["date"]).dt.date
            return df_filtered

        except Exception as e:
            print(f"\n⚠️ [{stock_id}] 財報抓取失敗: {e}")
            return None

    def _fetch_dividends(self, stock_id):
        """從 Yahoo Finance 抓取歷史配息"""
        ticker = f"{stock_id}.TW"
        try:
            stock = yf.Ticker(ticker)
            divs = stock.dividends

            if divs.empty:
                return None

            df = divs.reset_index()
            df.columns = ["date", "dividend"]
            df["stock_id"] = stock_id
            df["date"] = pd.to_datetime(df["date"]).dt.date
            return df[["date", "stock_id", "dividend"]]

        except Exception as e:
            print(f"\n⚠️ [{stock_id}] 股利抓取失敗: {e}")
            return None


if __name__ == "__main__":
    if "--test" in sys.argv:
        idx = sys.argv.index("--test")
        test_id = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "2330"
        scanner = FundamentalScanner()
        scanner.get_targets = lambda: [test_id]
        scanner.resume_table = None
        scanner.scan()
    else:
        FundamentalScanner().scan()
