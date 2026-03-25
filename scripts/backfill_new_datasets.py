"""
歷史資料回補腳本 — 回補新增 FinMind 資料集的歷史資料

Usage:
    uv run python scripts/backfill_new_datasets.py --dataset day_trading
    uv run python scripts/backfill_new_datasets.py --dataset chip_broker --start 2021-07-01
    uv run python scripts/backfill_new_datasets.py --dataset all --start 2023-01-01 --end 2026-03-23
    uv run python scripts/backfill_new_datasets.py --dataset cash_flows
    uv run python scripts/backfill_new_datasets.py --list
"""

import argparse
import sys
import os
import time
from datetime import date, datetime, timedelta

import pandas as pd
from tqdm import tqdm

# 確保能 import core/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.db import save_to_db, safe_read_sql
from core.finmind_client import get_fm_loader
from core.logger import setup_logger
from core.rate_limiter import RateLimiter

logger = setup_logger("backfill_new_datasets")


# ============================================================================
# 可回補資料集定義
# ============================================================================

AVAILABLE_DATASETS = {
    "day_trading": ("批量按日", "2014-01-01"),
    "chip_broker": ("批量按日", "2021-07-01"),
    "chip_gov_bank": ("批量按日", "2021-07-01"),
    "total_return_index": ("批量全拉", "2003-01-01"),
    "dividend_result": ("逐股", "2003-01-01"),
    "stock_delisting": ("一次性", None),
    "securities_trader_info": ("一次性", None),
    "cash_flows": ("逐股", "2020-01-01"),
}

# FinMind API 方法名對照
API_METHOD_MAP = {
    "day_trading": "taiwan_stock_day_trading",
    "chip_broker": "taiwan_stock_trading_daily_report",
    "chip_gov_bank": "taiwan_stock_government_bank_buy_sell",
    "total_return_index": "taiwan_stock_total_return_index",
    "dividend_result": "taiwan_stock_dividend_result",
    "stock_delisting": "taiwan_stock_delisting",
    "securities_trader_info": "taiwan_securities_trader_info",
}

# 免費 vs Sponsor 分類
FREE_DATASETS = [
    "day_trading", "total_return_index", "dividend_result",
    "stock_delisting", "securities_trader_info", "cash_flows",
]
SPONSOR_DATASETS_LIST = ["chip_broker", "chip_gov_bank"]


def _elapsed(t0: float) -> str:
    return f"{time.time() - t0:.2f}s"


def _generate_months(start_date: str, end_date: str) -> list[tuple[str, str]]:
    """生成月份區間列表: [(month_start, month_end), ...]"""
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    months = []
    current = start.replace(day=1)
    while current <= end:
        month_start = max(current, start)
        # 計算月底
        if current.month == 12:
            next_month = current.replace(year=current.year + 1, month=1, day=1)
        else:
            next_month = current.replace(month=current.month + 1, day=1)
        month_end = min(next_month - timedelta(days=1), end)
        months.append((month_start.strftime("%Y-%m-%d"), month_end.strftime("%Y-%m-%d")))
        current = next_month
    return months


def _generate_weekdays(start_date: str, end_date: str) -> list[str]:
    """生成工作日列表（排除週六日）"""
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    days = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return days


def _get_stock_list() -> list[str]:
    """從 twstock_code 取得一般股票清單"""
    try:
        df = safe_read_sql(
            "SELECT \"商品代號\" FROM twstock_code "
            "WHERE \"商品類型\" IN ('股票', 'ETF')"
        )
        return df["商品代號"].tolist()
    except Exception as e:
        logger.error(f"查詢 twstock_code 失敗: {e}")
        return []


# ============================================================================
# DatasetBackfiller
# ============================================================================

class DatasetBackfiller:
    """歷史資料回補器"""

    def __init__(self):
        self.fm_loader = get_fm_loader()
        self.limiter = RateLimiter(source="finmind")

    def backfill(self, dataset_name: str, start_date: str, end_date: str):
        """根據資料集名稱分派對應的回補方法"""
        logger.info(f"開始回補: {dataset_name} ({start_date} ~ {end_date})")
        t0 = time.time()

        if dataset_name in ("day_trading", "chip_gov_bank"):
            label = "當日沖銷" if dataset_name == "day_trading" else "官股行庫"
            total = self.backfill_batch_by_day(
                API_METHOD_MAP[dataset_name], dataset_name, label,
                start_date, end_date,
            )
        elif dataset_name == "chip_broker":
            total = self.backfill_broker(start_date, end_date)
        elif dataset_name == "total_return_index":
            total = self.backfill_total_return_index(start_date, end_date)
        elif dataset_name == "dividend_result":
            total = self.backfill_dividend_result(start_date, end_date)
        elif dataset_name == "stock_delisting":
            total = self.backfill_one_shot(
                API_METHOD_MAP[dataset_name], dataset_name, "下市櫃",
            )
        elif dataset_name == "securities_trader_info":
            total = self.backfill_one_shot(
                API_METHOD_MAP[dataset_name], dataset_name, "券商資訊",
            )
        elif dataset_name == "cash_flows":
            total = self.backfill_cash_flows(start_date)
        else:
            logger.error(f"未知的資料集: {dataset_name}")
            return

        logger.info(
            f"回補完成: {dataset_name} | 寫入 {total} 筆 | "
            f"耗時 {_elapsed(t0)}"
        )

    def backfill_batch_by_month(
        self, method_name: str, table_name: str, label: str,
        start_date: str, end_date: str,
    ) -> int:
        """批量 API 按月迭代回補"""
        months = _generate_months(start_date, end_date)
        total_rows = 0

        for month_start, month_end in tqdm(months, desc=label):
            try:
                fetch_fn = getattr(self.fm_loader, method_name)

                def _call(fn=fetch_fn, s=month_start, e=month_end):
                    return fn(start_date=s, end_date=e)

                df = self.limiter.call_with_retry(_call)
            except Exception as e:
                logger.error(f"[{label}] {month_start}~{month_end} 查詢失敗: {e}")
                self.limiter.wait()
                continue

            if df is None or df.empty:
                self.limiter.wait()
                continue

            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date

            ok = save_to_db(df, table_name, chunksize=1000)
            if ok:
                total_rows += len(df)
                logger.info(f"[{label}] {month_start}~{month_end}: {len(df)} 筆")
            self.limiter.wait()

        return total_rows

    def backfill_batch_by_day(
        self, method_name: str, table_name: str, label: str,
        start_date: str, end_date: str,
    ) -> int:
        """批量 API 按日迭代回補（用於 Sponsor 資料集）"""
        days = _generate_weekdays(start_date, end_date)
        total_rows = 0

        for day_str in tqdm(days, desc=label):
            try:
                fetch_fn = getattr(self.fm_loader, method_name)

                # gov_bank 只有 start_date；day_trading 有 start/end
                if method_name == "taiwan_stock_government_bank_buy_sell":
                    def _call(fn=fetch_fn, d=day_str):
                        return fn(start_date=d)
                else:
                    def _call(fn=fetch_fn, d=day_str):
                        return fn(start_date=d, end_date=d)

                df = self.limiter.call_with_retry(_call)
            except Exception as e:
                err_msg = str(e).lower()
                if "403" in err_msg or "permission" in err_msg or "sponsor" in err_msg:
                    logger.warning(f"[{label}] 需要 Sponsor 帳號，中止回補")
                    break
                logger.error(f"[{label}] {day_str} 查詢失敗: {e}")
                self.limiter.wait()
                continue

            if df is None or df.empty:
                self.limiter.wait()
                continue

            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date

            ok = save_to_db(df, table_name, chunksize=1000)
            if ok:
                total_rows += len(df)
            self.limiter.wait()

        logger.info(f"[{label}] 共寫入 {total_rows} 筆")
        return total_rows

    def backfill_one_shot(
        self, method_name: str, table_name: str, label: str,
    ) -> int:
        """一次性全拉靜態資料"""
        logger.info(f"[{label}] 一次性全拉 ...")
        try:
            fetch_fn = getattr(self.fm_loader, method_name)

            def _call(fn=fetch_fn):
                return fn()

            df = self.limiter.call_with_retry(_call)
        except Exception as e:
            logger.error(f"[{label}] API 異常: {e}")
            return 0

        if df is None or df.empty:
            logger.info(f"[{label}] API 回傳空資料")
            return 0

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date

        ok = save_to_db(df, table_name, chunksize=1000)
        row_count = len(df) if ok else 0
        logger.info(f"[{label}] 寫入 {row_count} 筆")
        return row_count

    def backfill_total_return_index(self, start_date: str, end_date: str) -> int:
        """含息報酬指數特殊處理（用 index_id 而非 stock_id）"""
        logger.info(f"[含息報酬指數] 一次性查詢 {start_date} ~ {end_date} ...")
        try:
            def _call():
                return self.fm_loader.taiwan_stock_total_return_index(
                    index_id="TAIEX", start_date=start_date, end_date=end_date,
                )

            df = self.limiter.call_with_retry(_call)
        except Exception as e:
            logger.error(f"[含息報酬指數] API 異常: {e}")
            return 0

        if df is None or df.empty:
            logger.info("[含息報酬指數] API 回傳空資料")
            return 0

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date

        ok = save_to_db(df, "total_return_index", chunksize=1000)
        row_count = len(df) if ok else 0
        logger.info(f"[含息報酬指數] 寫入 {row_count} 筆")
        return row_count

    # 8 大外資券商代碼
    FOREIGN_BROKERS = {
        "1650": "瑞銀", "1480": "高盛", "1470": "摩根士丹利",
        "8440": "摩根大通", "1440": "美林", "1590": "花旗環球",
        "1360": "麥格理", "1560": "野村",
    }

    def backfill_broker(self, start_date: str, end_date: str) -> int:
        """券商分點回補 — 按 securities_trader_id 查 8 大外資，聚合後寫入

        用 securities_trader_id 查詢可一次拿到該券商全市場交易，
        每天只需 8 次 API call（8 大外資），效率極高。
        聚合後每券商每股每天只存一筆（sum buy/sell）。
        """
        days = _generate_weekdays(start_date, end_date)
        total_rows = 0
        buffer = []
        flush_size = 5  # 每 5 天批量寫入

        broker_ids = list(self.FOREIGN_BROKERS.keys())
        logger.info(
            f"[券商分點] {len(broker_ids)} 家外資 × {len(days)} 天 "
            f"= {len(broker_ids) * len(days)} API calls"
        )

        for day_idx, day_str in enumerate(tqdm(days, desc="券商分點"), 1):
            for broker_id in broker_ids:
                try:
                    def _call(bid=broker_id, d=day_str):
                        return self.fm_loader.taiwan_stock_trading_daily_report(
                            securities_trader_id=bid, date=d,
                        )
                    df = self.limiter.call_with_retry(_call)
                except Exception as e:
                    err_msg = str(e).lower()
                    if "403" in err_msg or "permission" in err_msg:
                        logger.warning("[券商分點] 需要 Sponsor 帳號，中止")
                        if buffer:
                            merged = pd.concat(buffer, ignore_index=True)
                            self._aggregate_and_save_broker(merged)
                            total_rows += len(merged)
                        return total_rows
                    self.limiter.wait()
                    continue

                if df is not None and not df.empty:
                    if "date" in df.columns:
                        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
                    buffer.append(df)
                self.limiter.wait()

            # 每 flush_size 天批量聚合寫入
            if day_idx % flush_size == 0 or day_idx == len(days):
                if buffer:
                    merged = pd.concat(buffer, ignore_index=True)
                    rows_written = self._aggregate_and_save_broker(merged)
                    total_rows += rows_written
                    logger.info(
                        f"[券商分點] 批量寫入 {rows_written} 筆 (累計 {total_rows})"
                    )
                    buffer = []

        logger.info(f"[券商分點] 共寫入 {total_rows} 筆")
        return total_rows

    def _aggregate_and_save_broker(self, df: pd.DataFrame) -> int:
        """將原始分點資料聚合（每券商每股每天一筆）後寫入 DB"""
        agg = df.groupby(
            ["stock_id", "date", "securities_trader_id", "securities_trader"],
            as_index=False,
        ).agg(
            total_buy=("buy", "sum"),
            total_sell=("sell", "sum"),
        )
        agg["net"] = agg["total_buy"] - agg["total_sell"]
        ok = save_to_db(agg, "chip_broker", chunksize=5000)
        return len(agg) if ok else 0

    def backfill_dividend_result(self, start_date: str, end_date: str) -> int:
        """除息結果逐股回補（累積批量寫入，減少 IO）"""
        stocks = _get_stock_list()
        if not stocks:
            logger.error("[除息結果] 無法取得股票清單")
            return 0

        total_rows = 0
        buffer = []
        flush_size = 200  # 累積 200 支股票的資料後批量寫入

        for i, stock_id in enumerate(tqdm(stocks, desc="除息結果"), 1):
            try:
                def _call(sid=stock_id):
                    return self.fm_loader.taiwan_stock_dividend_result(
                        stock_id=sid, start_date=start_date, end_date=end_date,
                    )

                df = self.limiter.call_with_retry(_call)
            except Exception as e:
                logger.debug(f"[除息結果] {stock_id} 查詢失敗: {e}")
                self.limiter.wait()
                continue

            if df is not None and not df.empty:
                if "date" in df.columns:
                    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
                buffer.append(df)
            self.limiter.wait()

            # 累積到 flush_size 或最後一批，批量寫入
            if len(buffer) >= flush_size or i == len(stocks):
                if buffer:
                    merged = pd.concat(buffer, ignore_index=True)
                    ok = save_to_db(merged, "dividend_result", chunksize=5000)
                    if ok:
                        total_rows += len(merged)
                        logger.info(f"[除息結果] 批量寫入 {len(merged)} 筆 (累計 {total_rows})")
                    buffer = []

        logger.info(f"[除息結果] 共寫入 {total_rows} 筆")
        return total_rows

    def backfill_cash_flows(self, start_date: str) -> int:
        """現金流量表回補 — 逐股呼叫，篩選 FOCUS_METRICS"""
        from scanners.fundamental_scanner import FOCUS_METRICS

        stocks = _get_stock_list()
        if not stocks:
            logger.error("[現金流量表] 無法取得股票清單")
            return 0

        # 找出 FOCUS_METRICS 中現金流量相關的 type
        cash_flow_types = {
            "CashFlowsFromOperatingActivities",
            "CapitalExpenditure",
        }
        focus_set = set(FOCUS_METRICS) & cash_flow_types
        if not focus_set:
            logger.warning("[現金流量表] FOCUS_METRICS 中沒有現金流量相關 type")
            return 0

        total_rows = 0
        buffer = []
        flush_size = 200  # 累積 200 支股票的資料後批量寫入

        for i, stock_id in enumerate(tqdm(stocks, desc="現金流量表"), 1):
            try:
                def _call(sid=stock_id):
                    return self.fm_loader.taiwan_stock_cash_flows_statement(
                        stock_id=sid, start_date=start_date,
                    )

                df = self.limiter.call_with_retry(_call)
            except Exception as e:
                logger.debug(f"[現金流量表] {stock_id} 查詢失敗: {e}")
                self.limiter.wait()
                continue

            if df is not None and not df.empty:
                # 篩選 FOCUS_METRICS 中的 type
                if "type" in df.columns:
                    df = df[df["type"].isin(FOCUS_METRICS)]
                if not df.empty:
                    # 只保留 financial_reports 表需要的欄位
                    keep_cols = ["date", "stock_id", "type", "value"]
                    df = df[[c for c in keep_cols if c in df.columns]]
                    if "date" in df.columns:
                        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
                    buffer.append(df)
            self.limiter.wait()

            # 累積到 flush_size 或最後一批，批量寫入
            if len(buffer) >= flush_size or i == len(stocks):
                if buffer:
                    merged = pd.concat(buffer, ignore_index=True)
                    ok = save_to_db(merged, "financial_reports", chunksize=5000)
                    if ok:
                        total_rows += len(merged)
                        logger.info(f"[現金流量表] 批量寫入 {len(merged)} 筆 (累計 {total_rows})")
                    buffer = []

        logger.info(f"[現金流量表] 共寫入 {total_rows} 筆")
        return total_rows


# ============================================================================
# CLI
# ============================================================================

def _list_datasets():
    """列出所有可回補的資料集"""
    print("\n可回補的資料集:")
    print(f"{'資料集':<25s} {'回補方式':<12s} {'預設起始日期':<15s} {'類型':<8s}")
    print("-" * 65)
    for name, (method, default_start) in AVAILABLE_DATASETS.items():
        dtype = "Sponsor" if name in SPONSOR_DATASETS_LIST else "免費"
        start_str = default_start or "N/A (靜態)"
        print(f"{name:<25s} {method:<12s} {start_str:<15s} {dtype:<8s}")
    print()
    print("特殊選項:")
    print("  --dataset free      只回補免費資料集")
    print("  --dataset sponsor   只回補 Sponsor 資料集")
    print("  --dataset all       回補全部資料集")


def main():
    parser = argparse.ArgumentParser(
        description="歷史資料回補腳本 — 回補新增 FinMind 資料集",
    )
    parser.add_argument(
        "--dataset",
        choices=[*AVAILABLE_DATASETS.keys(), "all", "free", "sponsor"],
        help="要回補的資料集名稱",
    )
    parser.add_argument(
        "--start", type=str, default=None,
        help="起始日期 YYYY-MM-DD（覆寫預設）",
    )
    parser.add_argument(
        "--end", type=str, default=None,
        help="結束日期 YYYY-MM-DD（預設今天）",
    )
    parser.add_argument(
        "--list", action="store_true", dest="list_datasets",
        help="列出可回補的資料集",
    )
    args = parser.parse_args()

    if args.list_datasets:
        _list_datasets()
        return

    if not args.dataset:
        parser.print_help()
        return

    today_str = date.today().strftime("%Y-%m-%d")
    end_date = args.end or today_str

    # 決定要回補哪些資料集
    if args.dataset == "all":
        targets = list(AVAILABLE_DATASETS.keys())
    elif args.dataset == "free":
        targets = FREE_DATASETS
    elif args.dataset == "sponsor":
        targets = SPONSOR_DATASETS_LIST
    else:
        targets = [args.dataset]

    backfiller = DatasetBackfiller()

    for ds_name in targets:
        ds_method, ds_default_start = AVAILABLE_DATASETS[ds_name]
        start_date = args.start or ds_default_start

        if ds_method == "一次性":
            # 靜態資料不需要日期範圍
            backfiller.backfill(ds_name, "", "")
        else:
            if not start_date:
                logger.error(f"[{ds_name}] 需要指定 --start 起始日期")
                continue
            backfiller.backfill(ds_name, start_date, end_date)

        print()  # 資料集間空行


if __name__ == "__main__":
    main()
