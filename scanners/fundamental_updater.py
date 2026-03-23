"""
季報自動增量更新 — 以 DB 差集策略逐股抓取缺漏季報

核心邏輯：
1. 根據日期推算「DB 應有的最新季報 date」（expected_latest_quarter）
2. 從 twstock_code 取全市場普通股，與 financial_reports 比對差集
3. 逐股呼叫 FinMind API 抓取損益表 + 資產負債表
4. 連續 10 次失敗自動中止（熔斷）

季報公布月（2/3/5/8/11）每天跑，越跑越快，DB Unique Key 自動去重。

Usage:
    python -m scanners.fundamental_updater                   # 預設今天
    python -m scanners.fundamental_updater --date 2026-03-23  # 指定日期
    python -m scanners.fundamental_updater --force            # 強制執行（跳過月份檢查）
"""
import argparse
import time
from datetime import date, datetime

import pandas as pd

from core.alert_manager import log_scanner_run
from core.db import safe_read_sql, save_to_db
from core.finmind_client import get_fm_loader
from core.logger import setup_logger
from core.rate_limiter import RateLimiter
from scanners.fundamental_scanner import FOCUS_METRICS

logger = setup_logger("fundamental_updater")

# 季報公布月份
QUARTERLY_REPORT_MONTHS = {2, 3, 5, 8, 11}

# FinMind 查詢起始日（足夠涵蓋近期季報）
FETCH_START_DATE = "2024-01-01"

# 連續失敗熔斷閾值
CIRCUIT_BREAKER_THRESHOLD = 10


def expected_latest_quarter(today: date) -> date:
    """根據日期推算 DB 應有的最新季報 date（季末日）。

    各季法定公布期限：
    - Q1 (3/31): 5/15 前公布 → 5/15 起應有 Q1
    - Q2 (6/30): 8/14 前公布 → 8/14 起應有 Q2
    - Q3 (9/30): 11/14 前公布 → 11/14 起應有 Q3
    - Q4 (12/31): 3/31 前公布 → 3/1 起應有 Q4（保守估計）

    1/1~2/28: 上年 Q3 (9/30)
    3/1~5/14: 上年 Q4 (12/31)
    5/15~8/13: 當年 Q1 (3/31)
    8/14~11/13: 當年 Q2 (6/30)
    11/14~12/31: 當年 Q3 (9/30)
    """
    year = today.year
    month = today.month
    day = today.day

    if month >= 11 and day >= 14:
        return date(year, 9, 30)
    elif month >= 8 and (month > 8 or day >= 14):
        return date(year, 6, 30)
    elif month >= 5 and (month > 5 or day >= 15):
        return date(year, 3, 31)
    elif month >= 3:
        return date(year - 1, 12, 31)
    else:
        return date(year - 1, 9, 30)


def is_quarterly_report_month(today: date) -> bool:
    """判斷是否為季報公布月（2/3/5/8/11）。"""
    return today.month in QUARTERLY_REPORT_MONTHS


def get_missing_stocks(expected_qtr: date) -> list[str]:
    """從 twstock_code 取全市場普通股，比對 financial_reports 取差集。

    Returns:
        缺少最新季報的 stock_id 列表
    """
    # 全市場普通股
    try:
        df_all = safe_read_sql(
            "SELECT \"商品代號\" AS stock_id FROM twstock_code "
            "WHERE \"商品類型\" = '股票'"
        )
    except Exception as e:
        logger.error(f"查詢 twstock_code 失敗: {e}")
        return []

    all_stocks = set(df_all["stock_id"].astype(str).tolist())

    # 已有最新季報的 stock_id
    qtr_str = expected_qtr.strftime("%Y-%m-%d")
    try:
        df_existing = safe_read_sql(
            "SELECT DISTINCT stock_id FROM financial_reports "
            "WHERE date >= :qtr_date",
            params={"qtr_date": qtr_str},
        )
        existing_stocks = set(df_existing["stock_id"].astype(str).tolist())
    except Exception as e:
        logger.error(f"查詢 financial_reports 失敗: {e}")
        return list(all_stocks)

    missing = sorted(all_stocks - existing_stocks)
    return missing


class FundamentalUpdater:
    """季報增量更新器"""

    def __init__(self):
        self.fm_loader = get_fm_loader()
        self.limiter = RateLimiter(source="finmind_fast")

    def run(self, target_date=None, force=False):
        """主入口。

        Args:
            target_date: date 或 'YYYY-MM-DD'，None 表示今天
            force: True 跳過月份檢查
        """
        if target_date is None:
            target_date = date.today()
        elif isinstance(target_date, str):
            target_date = datetime.strptime(target_date, "%Y-%m-%d").date()

        run_start = time.time()
        logger.info(f"{'='*60}")
        logger.info(f"季報增量更新開始: {target_date}")
        logger.info(f"{'='*60}")

        # Step 1: 月份檢查
        if not force and not is_quarterly_report_month(target_date):
            logger.info(
                f"非季報公布月（{target_date.month} 月），跳過更新。"
                f"使用 --force 可強制執行。"
            )
            return

        # Step 2: 計算預期最新季報
        expected_qtr = expected_latest_quarter(target_date)
        logger.info(f"預期最新季報: {expected_qtr}")

        # Step 3: 取差集
        missing = get_missing_stocks(expected_qtr)
        if not missing:
            logger.info("所有股票已有最新季報，無需更新。")
            self._log_run(target_date, run_start, 0, 0, 0)
            return

        logger.info(f"缺少最新季報的股票: {len(missing)} 支")

        # Step 4: 逐股抓取
        success_count = 0
        fail_count = 0
        consecutive_failures = 0

        for i, stock_id in enumerate(missing, 1):
            if consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
                logger.error(
                    f"連續 {CIRCUIT_BREAKER_THRESHOLD} 次失敗，觸發熔斷，"
                    f"已完成 {i-1}/{len(missing)}"
                )
                break

            ok = self._fetch_one(stock_id)
            if ok:
                success_count += 1
                consecutive_failures = 0
            else:
                fail_count += 1
                consecutive_failures += 1

            if i % 100 == 0:
                logger.info(
                    f"進度: {i}/{len(missing)} | "
                    f"成功: {success_count} | 失敗: {fail_count}"
                )

        # Step 5: 結算
        elapsed = time.time() - run_start
        logger.info(f"{'='*60}")
        logger.info(
            f"季報增量更新完成 | "
            f"差集: {len(missing)} | 成功: {success_count} | "
            f"失敗: {fail_count} | 耗時: {elapsed:.1f}s"
        )
        logger.info(f"{'='*60}")

        self._log_run(target_date, run_start, len(missing), success_count, fail_count)

    def _fetch_one(self, stock_id: str) -> bool:
        """抓取單支股票的損益表 + 資產負債表，寫入 DB。"""
        try:
            def _call_income():
                return self.fm_loader.taiwan_stock_financial_statement(
                    stock_id=stock_id, start_date=FETCH_START_DATE,
                )

            def _call_balance():
                return self.fm_loader.taiwan_stock_balance_sheet(
                    stock_id=stock_id, start_date=FETCH_START_DATE,
                )

            df_income = self.limiter.call_with_retry(_call_income)
            self.limiter.wait()
            df_balance = self.limiter.call_with_retry(_call_balance)
            self.limiter.wait()
        except Exception as e:
            logger.error(f"[{stock_id}] API 異常: {e}")
            return False

        # 合併
        df_list = []
        if df_income is not None and not df_income.empty:
            df_list.append(df_income)
        if df_balance is not None and not df_balance.empty:
            df_list.append(df_balance)

        if not df_list:
            # API 成功但無資料（如 ETF），視為成功
            return True

        df_all = pd.concat(df_list, ignore_index=True)
        df_all["type"] = df_all["type"].astype(str).str.strip()
        df_filtered = df_all[df_all["type"].isin(FOCUS_METRICS)].copy()

        if df_filtered.empty:
            return True

        df_filtered = df_filtered[["date", "stock_id", "type", "value"]]
        df_filtered["date"] = pd.to_datetime(df_filtered["date"]).dt.date

        ok = save_to_db(df_filtered, "financial_reports")
        if not ok:
            logger.error(f"[{stock_id}] DB 寫入失敗")
        return ok

    def _log_run(self, target_date, run_start, total, success, fail):
        """記錄執行日誌"""
        try:
            log_scanner_run(
                scanner_name="fundamental_updater",
                run_date=target_date.strftime("%Y-%m-%d"),
                started_at=datetime.fromtimestamp(run_start).isoformat(),
                finished_at=datetime.now().isoformat(),
                total_stocks=total,
                success_count=success,
                fail_count=fail,
                elapsed_seconds=round(time.time() - run_start, 1),
            )
        except Exception as e:
            logger.error(f"記錄執行日誌失敗（不影響主流程）: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="季報自動增量更新")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="指定日期 (YYYY-MM-DD)，預設為今天",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="強制執行（跳過月份檢查）",
    )
    args = parser.parse_args()
    FundamentalUpdater().run(target_date=args.date, force=args.force)
