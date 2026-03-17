"""
每日增量更新 — 批量取得全市場當日價格 + 籌碼資料

核心優化：FinMind 支援不帶 stock_id 的批量查詢，一次取得所有股票某日資料。
原本 1826 × 7 = 12,782 次 API 呼叫，縮減為 7 次，耗時從 12.5 小時降至 < 1 分鐘。

Usage:
    python -m scanners.daily_updater                  # 更新今天
    python -m scanners.daily_updater --date 2026-02-16  # 更新指定日期
"""
import argparse
from datetime import date, datetime

import pandas as pd

from core.db import save_to_db
from core.finmind_client import get_fm_loader
from core.logger import setup_logger
from core.rate_limiter import RateLimiter
from scanners.chip_scanner import CHIP_DATASETS, _pivot_institutional

logger = setup_logger("daily_updater")


class DailyUpdater:
    """每日增量更新：批量取得所有股票的價格 + 籌碼資料"""

    def __init__(self):
        self.fm_loader = get_fm_loader()
        self.limiter = RateLimiter(source="finmind")

    def run(self, target_date=None):
        """主入口，預設抓今天。

        Args:
            target_date: date 物件或 'YYYY-MM-DD' 字串，None 表示今天
        """
        if target_date is None:
            target_date = date.today()
        elif isinstance(target_date, str):
            target_date = datetime.strptime(target_date, "%Y-%m-%d").date()

        date_str = target_date.strftime("%Y-%m-%d")
        logger.info(f"=== 每日更新開始: {date_str} ===")

        # 1. 價格資料
        price_result = self._fetch_price(date_str)
        if price_result == "no_data":
            logger.info(f"{date_str} 無價格資料（非交易日），跳過全部更新")
            return False

        price_ok = price_result == "ok"
        if not price_ok:
            logger.warning(f"{date_str} 價格資料寫入失敗，仍繼續更新籌碼資料")

        # 2. 籌碼資料（6 個 dataset）
        chip_results = self._fetch_chip(date_str)

        # 3. 結算報告
        success_count = (1 if price_ok else 0) + sum(chip_results.values())
        total_count = 1 + len(CHIP_DATASETS)
        logger.info(
            f"=== 每日更新完成: {date_str} | "
            f"成功 {success_count}/{total_count} 個 dataset ==="
        )
        return True

    def _fetch_price(self, date_str):
        """批量取得全市場當日價格。

        回傳:
            "ok"         — 取得資料且寫入成功
            "no_data"    — 無資料（非交易日）
            "write_error" — 取得資料但寫入失敗
        """
        logger.info(f"[價格] 批量查詢 {date_str} ...")

        try:
            def _call():
                return self.fm_loader.taiwan_stock_daily(
                    start_date=date_str, end_date=date_str
                )

            df = self.limiter.call_with_retry(_call)
        except Exception as e:
            logger.error(f"[價格] 查詢失敗: {e}")
            return "no_data"

        if df is None or df.empty:
            return "no_data"

        # 欄位映射: FinMind → daily_price schema
        col_map = {
            "max": "high",
            "min": "low",
            "Trading_Volume": "volume",
        }
        df = df.rename(columns=col_map)

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.date

        keep_cols = ["date", "stock_id", "open", "high", "low", "close", "volume"]
        df = df[[c for c in keep_cols if c in df.columns]]

        ok = save_to_db(df, "daily_price", chunksize=1000)
        row_count = len(df) if ok else 0
        logger.info(f"[價格] 寫入 {row_count} 筆")
        self.limiter.wait()
        return "ok" if ok else "write_error"

    def _fetch_chip(self, date_str):
        """批量取得 6 個籌碼 dataset。回傳 dict: {table_name: bool}。"""
        results = {}

        for method_name, table_name, label in CHIP_DATASETS:
            logger.info(f"[{label}] 批量查詢 {date_str} ...")

            try:
                fetch_fn = getattr(self.fm_loader, method_name)

                def _call(fn=fetch_fn):
                    return fn(start_date=date_str, end_date=date_str)

                df = self.limiter.call_with_retry(_call)
            except Exception as e:
                logger.error(f"[{label}] 查詢失敗: {e}")
                results[table_name] = False
                self.limiter.wait()
                continue

            if df is None or df.empty:
                logger.info(f"[{label}] 無資料")
                results[table_name] = False
                self.limiter.wait()
                continue

            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"]).dt.date

            # 三大法人需 pivot
            if table_name == "chip_institutional":
                df = _pivot_institutional(df)

            ok = save_to_db(df, table_name)
            row_count = len(df) if ok else 0
            logger.info(f"[{label}] 寫入 {row_count} 筆")
            results[table_name] = ok
            self.limiter.wait()

        return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="每日增量更新（批量模式）")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="指定日期 (YYYY-MM-DD)，預設為今天",
    )
    args = parser.parse_args()
    DailyUpdater().run(target_date=args.date)
