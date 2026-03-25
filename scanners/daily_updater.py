"""
每日增量更新 — 批量取得全市場當日價格 + 籌碼 + 估值面 + 月營收資料

核心優化：FinMind 支援不帶 stock_id 的批量查詢，一次取得所有股票某日資料。
原本 1826 × 7 = 12,782 次 API 呼叫，縮減為 8 次，耗時從 12.5 小時降至 < 1 分鐘。

月營收特殊處理：各公司公布時間不同（法定期限為次月 10 號），
每天都抓最近 2 個月資料，DB Unique Key 自動去重，確保不遺漏晚公布的公司。

Usage:
    python -m scanners.daily_updater                  # 更新今天
    python -m scanners.daily_updater --date 2026-02-16  # 更新指定日期
"""
import argparse
import json
import time
import urllib.request
from datetime import date, datetime, timedelta

import pandas as pd

from core.db import save_to_db
from core.finmind_client import get_fm_loader
from core.logger import setup_logger
from core.rate_limiter import RateLimiter
from scanners.chip_scanner import CHIP_DATASETS, _pivot_institutional

logger = setup_logger("daily_updater")

# 新增每日資料集：(DataLoader 方法名, DB 表名, 標籤說明)
DAILY_NEW_DATASETS = [
    ("taiwan_stock_day_trading", "day_trading", "當日沖銷"),
]

# Sponsor 限定資料集（需 Sponsor 帳號才能取得）
SPONSOR_DATASETS = [
    ("taiwan_stock_trading_daily_report", "chip_broker", "券商分點"),
    ("taiwan_stock_government_bank_buy_sell", "chip_gov_bank", "官股行庫"),
]


# ============================================================================
# 交易日判斷（TWSE 開休市行事曆）
# ============================================================================

def _fetch_twse_holidays(year: int) -> set[str]:
    """從 TWSE 官方 API 取得該年度休市日期集合。

    來源: https://www.twse.com.tw/holidaySchedule/holidaySchedule?response=json
    回傳格式: {"2026-01-01", "2026-02-15", ...}
    """
    url = (
        "https://www.twse.com.tw/holidaySchedule/holidaySchedule"
        f"?response=json&queryYear={year}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        logger.warning(f"TWSE 行事曆 API 查詢失敗: {e}")
        return set()

    holidays = set()
    for row in data.get("data", []):
        date_str, name = row[0], row[1]
        # 含「交易」字樣的是交易日標記，不是休市日
        if "交易" in name or "市場無交易" in name:
            continue
        holidays.add(date_str)
    return holidays


def is_trading_day(target_date: date) -> tuple[bool, str]:
    """判斷指定日期是否為台股交易日。

    回傳: (is_trading: bool, reason: str)
    判斷邏輯：
      1. 週六/日 → 非交易日
      2. TWSE 休市行事曆命中 → 非交易日
      3. 其餘 → 交易日（TWSE API 失敗時 fallback 為週一至五皆視為交易日）
    """
    weekday = target_date.weekday()
    if weekday >= 5:
        day_name = "週六" if weekday == 5 else "週日"
        return False, f"{day_name}，非交易日"

    date_str = target_date.strftime("%Y-%m-%d")
    holidays = _fetch_twse_holidays(target_date.year)

    if not holidays:
        return True, "TWSE 行事曆 API 無回應，fallback 視為交易日（週一至五）"

    if date_str in holidays:
        return False, f"TWSE 公告休市日"

    return True, "交易日（TWSE 行事曆確認）"


# ============================================================================
# DailyUpdater
# ============================================================================

class DailyUpdater:
    """每日增量更新：批量取得所有股票的價格 + 籌碼 + 估值面資料"""

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
        run_start = time.time()
        logger.info(f"{'='*60}")
        logger.info(f"每日更新開始: {date_str} ({_weekday_name(target_date)})")
        logger.info(f"{'='*60}")

        # Step 0: 交易日判斷
        trading, reason = is_trading_day(target_date)
        logger.info(f"[交易日檢查] {date_str} → {reason}")
        if not trading:
            logger.info(f"非交易日，跳過全部更新（耗時 {_elapsed(run_start)}）")
            return False

        # Step 1: 價格資料
        price_result = self._fetch_price(date_str)
        if price_result == "no_data":
            logger.warning(
                f"[價格] TWSE 判定為交易日但 FinMind 無價格資料 — "
                f"可能資料尚未發布或 API 延遲"
            )
            # 仍然繼續抓其他資料，不直接 return False
        if price_result == "api_error":
            logger.error(f"[價格] API 查詢失敗，繼續執行其他 dataset")

        price_ok = price_result == "ok"

        # Step 2: 籌碼資料（6 個 dataset）
        chip_results = self._fetch_chip(date_str)

        # Step 3: 估值面資料（stock_per + market_value）
        valuation_results = self._backfill_valuation(date_str)

        # Step 4: 月營收（每天抓最近 2 個月，DB Unique Key 自動去重）
        # 各公司公布時間不同（法定期限次月 10 號），每天抓確保不遺漏晚公布的公司
        revenue_ok = self._fetch_revenue(target_date)

        # Step 5: 新增每日資料集（當沖等）
        new_daily_results = self._fetch_new_daily(date_str)

        # Step 6: Sponsor 資料集（券商分點、官股行庫）
        sponsor_results = self._fetch_sponsor(date_str)

        # Step 7: 含息報酬指數（市場級，每日更新）
        tri_ok = self._fetch_total_return_index(date_str)

        # Step 8: 結算報告
        valuation_ok = sum(valuation_results.values())
        new_daily_ok = sum(new_daily_results.values())
        sponsor_ok = sum(sponsor_results.values())
        success_count = (
            (1 if price_ok else 0)
            + sum(chip_results.values())
            + valuation_ok
            + (1 if revenue_ok else 0)
            + new_daily_ok
            + sponsor_ok
            + (1 if tri_ok else 0)
        )
        total_count = (
            1 + len(CHIP_DATASETS) + len(valuation_results) + 1
            + len(DAILY_NEW_DATASETS) + len(SPONSOR_DATASETS) + 1
        )

        sep = "=" * 60
        logger.info(sep)
        logger.info(
            f"每日更新完成: {date_str} | "
            f"成功 {success_count}/{total_count} 個 dataset | "
            f"總耗時 {_elapsed(run_start)}"
        )
        # 逐項列出結果
        price_mark = "v" if price_ok else "x"
        logger.info(f"  [價格]           {price_mark} ({price_result})")
        for _, table_name, label in CHIP_DATASETS:
            ok = chip_results.get(table_name, False)
            mark = "v" if ok else "x"
            logger.info(f"  [{label:10s}]  {mark}")
        for _, table_name, label in self.VALUATION_DATASETS:
            ok = valuation_results.get(table_name, False)
            mark = "v" if ok else "x"
            logger.info(f"  [{label:10s}]  {mark}")
        revenue_mark = "v" if revenue_ok else "x"
        logger.info(f"  [月營收        ]  {revenue_mark}")
        for _, table_name, label in DAILY_NEW_DATASETS:
            ok = new_daily_results.get(table_name, False)
            mark = "v" if ok else "x"
            logger.info(f"  [{label:10s}]  {mark}")
        for _, table_name, label in SPONSOR_DATASETS:
            ok = sponsor_results.get(table_name, False)
            mark = "v" if ok else "x"
            logger.info(f"  [{label:10s}]  {mark}")
        tri_mark = "v" if tri_ok else "x"
        logger.info(f"  [含息報酬指數  ]  {tri_mark}")
        logger.info(sep)

        return True

    # ------------------------------------------------------------------
    # 價格
    # ------------------------------------------------------------------

    def _fetch_price(self, date_str):
        """批量取得全市場當日價格。

        回傳:
            "ok"         — 取得資料且寫入成功
            "no_data"    — 無資料（非交易日或資料未發布）
            "api_error"  — API 查詢失敗（配額/網路等）
            "write_error" — 取得資料但寫入失敗
        """
        t0 = time.time()
        logger.info(f"[價格] 批量查詢 {date_str} ...")

        try:
            def _call():
                return self.fm_loader.taiwan_stock_daily(
                    start_date=date_str, end_date=date_str
                )

            df = self.limiter.call_with_retry(_call)
        except Exception as e:
            logger.error(f"[價格] API 異常: {type(e).__name__}: {e} (耗時 {_elapsed(t0)})")
            return "api_error"

        if df is None:
            logger.info(f"[價格] API 回傳 None (耗時 {_elapsed(t0)})")
            return "no_data"
        if df.empty:
            logger.info(f"[價格] API 回傳空 DataFrame (耗時 {_elapsed(t0)})")
            return "no_data"

        logger.info(
            f"[價格] API 回傳 {len(df)} 筆, "
            f"欄位: {list(df.columns)}, "
            f"stock_id 數: {df['stock_id'].nunique() if 'stock_id' in df.columns else '?'} "
            f"(耗時 {_elapsed(t0)})"
        )

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

        t1 = time.time()
        ok = save_to_db(df, "daily_price", chunksize=1000)
        row_count = len(df) if ok else 0
        logger.info(f"[價格] DB 寫入 {'成功' if ok else '失敗'}: {row_count} 筆 (耗時 {_elapsed(t1)})")
        self.limiter.wait()
        return "ok" if ok else "write_error"

    # ------------------------------------------------------------------
    # 籌碼
    # ------------------------------------------------------------------

    def _fetch_chip(self, date_str):
        """批量取得 6 個籌碼 dataset。回傳 dict: {table_name: bool}。"""
        results = {}

        for method_name, table_name, label in CHIP_DATASETS:
            t0 = time.time()
            logger.info(f"[{label}] 批量查詢 {date_str} ...")

            try:
                fetch_fn = getattr(self.fm_loader, method_name)

                def _call(fn=fetch_fn):
                    return fn(start_date=date_str, end_date=date_str)

                df = self.limiter.call_with_retry(_call)
            except Exception as e:
                logger.error(
                    f"[{label}] API 異常: {type(e).__name__}: {e} "
                    f"(耗時 {_elapsed(t0)})"
                )
                results[table_name] = False
                self.limiter.wait()
                continue

            if df is None or df.empty:
                status = "None" if df is None else "空 DataFrame"
                logger.info(f"[{label}] API 回傳 {status} (耗時 {_elapsed(t0)})")
                results[table_name] = False
                self.limiter.wait()
                continue

            logger.info(
                f"[{label}] API 回傳 {len(df)} 筆, "
                f"欄位: {list(df.columns)} "
                f"(耗時 {_elapsed(t0)})"
            )

            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"]).dt.date

            # 三大法人需 pivot
            if table_name == "chip_institutional":
                df = _pivot_institutional(df)

            t1 = time.time()
            ok = save_to_db(df, table_name)
            row_count = len(df) if ok else 0
            logger.info(
                f"[{label}] DB 寫入 {'成功' if ok else '失敗'}: {row_count} 筆 "
                f"(耗時 {_elapsed(t1)})"
            )
            results[table_name] = ok
            self.limiter.wait()

        return results

    # ------------------------------------------------------------------
    # 估值面
    # ------------------------------------------------------------------

    VALUATION_DATASETS = [
        ("taiwan_stock_per_pbr", "stock_per", "本益比/股價淨值比/殖利率"),
        ("taiwan_stock_market_value", "market_value", "市值"),
    ]

    def _backfill_valuation(self, date_str):
        """批量取得當日 stock_per + market_value。回傳 dict: {table_name: bool}。"""
        results = {}

        for method_name, table_name, label in self.VALUATION_DATASETS:
            t0 = time.time()
            logger.info(f"[{label}] 批量查詢 {date_str} ...")

            try:
                fetch_fn = getattr(self.fm_loader, method_name)

                def _call(fn=fetch_fn):
                    return fn(start_date=date_str, end_date=date_str)

                df = self.limiter.call_with_retry(_call)
            except Exception as e:
                logger.error(
                    f"[{label}] API 異常: {type(e).__name__}: {e} "
                    f"(耗時 {_elapsed(t0)})"
                )
                results[table_name] = False
                self.limiter.wait()
                continue

            if df is None or df.empty:
                status = "None" if df is None else "空 DataFrame"
                logger.info(f"[{label}] API 回傳 {status} (耗時 {_elapsed(t0)})")
                results[table_name] = False
                self.limiter.wait()
                continue

            logger.info(
                f"[{label}] API 回傳 {len(df)} 筆, "
                f"欄位: {list(df.columns)}, "
                f"stock_id 數: {df['stock_id'].nunique() if 'stock_id' in df.columns else '?'} "
                f"(耗時 {_elapsed(t0)})"
            )

            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"]).dt.date

            t1 = time.time()
            ok = save_to_db(df, table_name)
            row_count = len(df) if ok else 0
            logger.info(
                f"[{label}] DB 寫入 {'成功' if ok else '失敗'}: {row_count} 筆 "
                f"(耗時 {_elapsed(t1)})"
            )
            results[table_name] = ok
            self.limiter.wait()

        return results

    # ------------------------------------------------------------------
    # 月營收（每天抓，DB 去重）
    # ------------------------------------------------------------------

    def _fetch_revenue(self, target_date):
        """批量抓取最近 2 個月的月營收。

        各公司公布上月營收的時間不同（法定期限為次月 10 號），
        因此每天都抓最近 2 個月的資料，由 DB Unique Key (stock_id, date, country)
        自動去重（INSERT ... ON CONFLICT DO NOTHING）。
        這樣可確保：
        - 早公布的公司：第一天就入庫，後續重複資料被 skip
        - 晚公布的公司：延遲幾天後入庫，不會遺漏

        API 成本：單次批量 call < 1 秒，每日多一次完全可接受。
        """
        # 往前推 60 天，確保涵蓋前 2 個月的營收公布期
        fetch_start = (target_date - timedelta(days=60)).strftime("%Y-%m-%d")
        fetch_end = target_date.strftime("%Y-%m-%d")

        t0 = time.time()
        logger.info(f"[月營收] 批量查詢 {fetch_start} ~ {fetch_end} ...")

        try:
            fetch_fn = self.fm_loader.taiwan_stock_month_revenue

            def _call():
                return fetch_fn(start_date=fetch_start, end_date=fetch_end)

            df = self.limiter.call_with_retry(_call)
        except Exception as e:
            logger.error(
                f"[月營收] API 異常: {type(e).__name__}: {e} "
                f"(耗時 {_elapsed(t0)})"
            )
            self.limiter.wait()
            return False

        if df is None or df.empty:
            status = "None" if df is None else "空 DataFrame"
            logger.info(f"[月營收] API 回傳 {status} (耗時 {_elapsed(t0)})")
            self.limiter.wait()
            return False

        logger.info(
            f"[月營收] API 回傳 {len(df)} 筆, "
            f"stock_id 數: {df['stock_id'].nunique() if 'stock_id' in df.columns else '?'} "
            f"(耗時 {_elapsed(t0)})"
        )

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.date

        t1 = time.time()
        ok = save_to_db(df, "month_revenue")
        logger.info(
            f"[月營收] DB 寫入 {'成功' if ok else '失敗'}: {len(df) if ok else 0} 筆 "
            f"(耗時 {_elapsed(t1)})"
        )
        self.limiter.wait()
        return ok

    # ------------------------------------------------------------------
    # 新增每日資料集（當沖等）
    # ------------------------------------------------------------------

    def _fetch_new_daily(self, date_str):
        """批量取得新增每日資料集。回傳 dict: {table_name: bool}。"""
        results = {}

        for method_name, table_name, label in DAILY_NEW_DATASETS:
            t0 = time.time()
            logger.info(f"[{label}] 批量查詢 {date_str} ...")

            try:
                fetch_fn = getattr(self.fm_loader, method_name)

                def _call(fn=fetch_fn):
                    return fn(start_date=date_str, end_date=date_str)

                df = self.limiter.call_with_retry(_call)
            except Exception as e:
                etype = type(e).__name__
                logger.error(
                    f"[{label}] API 異常: {etype}: {e} "
                    f"(耗時 {_elapsed(t0)})"
                )
                results[table_name] = False
                self.limiter.wait()
                continue

            if df is None or df.empty:
                status = "None" if df is None else "空 DataFrame"
                logger.info(f"[{label}] API 回傳 {status} (耗時 {_elapsed(t0)})")
                results[table_name] = False
                self.limiter.wait()
                continue

            logger.info(
                f"[{label}] API 回傳 {len(df)} 筆, "
                f"欄位: {list(df.columns)} "
                f"(耗時 {_elapsed(t0)})"
            )

            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"]).dt.date

            t1 = time.time()
            ok = save_to_db(df, table_name)
            row_count = len(df) if ok else 0
            logger.info(
                f"[{label}] DB 寫入 {'成功' if ok else '失敗'}: {row_count} 筆 "
                f"(耗時 {_elapsed(t1)})"
            )
            results[table_name] = ok
            self.limiter.wait()

        return results

    # ------------------------------------------------------------------
    # Sponsor 資料集（券商分點、官股行庫）
    # ------------------------------------------------------------------

    # 8 大外資券商代碼
    FOREIGN_BROKERS = {
        "1650": "瑞銀", "1480": "高盛", "1470": "摩根士丹利",
        "8440": "摩根大通", "1440": "美林", "1590": "花旗環球",
        "1360": "麥格理", "1560": "野村",
    }

    def _fetch_sponsor(self, date_str):
        """取得 Sponsor 限定資料集。
        broker: 用 securities_trader_id 查 8 大外資，聚合後寫入。
        gov_bank: 用 start_date 全市場查詢。
        權限不足時靜默跳過，log warning。
        回傳 dict: {table_name: bool}。
        """
        results = {}

        # --- 券商分點（8 大外資聚合）---
        t0 = time.time()
        logger.info(f"[券商分點] 查詢 {date_str}（8 大外資）...")
        broker_ok = self._fetch_broker_aggregated(date_str)
        results["chip_broker"] = broker_ok

        # --- 官股行庫 ---
        for method_name, table_name, label in SPONSOR_DATASETS:
            if table_name == "chip_broker":
                continue  # 已在上面處理
            t0 = time.time()
            logger.info(f"[{label}] 查詢 {date_str} ...")

            try:
                fetch_fn = getattr(self.fm_loader, method_name)

                def _call(fn=fetch_fn, d=date_str):
                    return fn(start_date=d)

                df = self.limiter.call_with_retry(_call)
            except Exception as e:
                err_msg = str(e).lower()
                if "403" in err_msg or "permission" in err_msg or "sponsor" in err_msg:
                    logger.warning(
                        f"[{label}] 需要 Sponsor 帳號，跳過 (耗時 {_elapsed(t0)})"
                    )
                    results[table_name] = False
                    self.limiter.wait()
                    continue
                etype = type(e).__name__
                logger.error(
                    f"[{label}] API 異常: {etype}: {e} "
                    f"(耗時 {_elapsed(t0)})"
                )
                results[table_name] = False
                self.limiter.wait()
                continue

            if df is None or df.empty:
                status = "None" if df is None else "空 DataFrame"
                logger.info(f"[{label}] API 回傳 {status} (耗時 {_elapsed(t0)})")
                results[table_name] = False
                self.limiter.wait()
                continue

            logger.info(
                f"[{label}] API 回傳 {len(df)} 筆, "
                f"欄位: {list(df.columns)} "
                f"(耗時 {_elapsed(t0)})"
            )

            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"]).dt.date

            t1 = time.time()
            ok = save_to_db(df, table_name)
            row_count = len(df) if ok else 0
            logger.info(
                f"[{label}] DB 寫入 {'成功' if ok else '失敗'}: {row_count} 筆 "
                f"(耗時 {_elapsed(t1)})"
            )
            results[table_name] = ok
            self.limiter.wait()

        return results

    # ------------------------------------------------------------------
    # 券商分點（8 大外資聚合）
    # ------------------------------------------------------------------

    def _fetch_broker_aggregated(self, date_str):
        """用 securities_trader_id 查 8 大外資，聚合後寫入 chip_broker。

        每天 8 次 API call，聚合後每券商每股一筆。
        回傳 bool。
        """
        t0 = time.time()
        buffer = []

        for broker_id, broker_name in self.FOREIGN_BROKERS.items():
            try:
                def _call(bid=broker_id, d=date_str):
                    return self.fm_loader.taiwan_stock_trading_daily_report(
                        securities_trader_id=bid, date=d,
                    )
                df = self.limiter.call_with_retry(_call)
            except Exception as e:
                err_msg = str(e).lower()
                if "403" in err_msg or "permission" in err_msg:
                    logger.warning(
                        f"[券商分點] 需要 Sponsor 帳號，跳過 (耗時 {_elapsed(t0)})"
                    )
                    return False
                logger.error(f"[券商分點] {broker_name} 查詢失敗: {e}")
                self.limiter.wait()
                continue

            if df is not None and not df.empty:
                if "date" in df.columns:
                    df["date"] = pd.to_datetime(df["date"]).dt.date
                buffer.append(df)
            self.limiter.wait()

        if not buffer:
            logger.info(f"[券商分點] 無資料 (耗時 {_elapsed(t0)})")
            return False

        merged = pd.concat(buffer, ignore_index=True)
        # 聚合：每券商每股每天一筆
        agg = merged.groupby(
            ["stock_id", "date", "securities_trader_id", "securities_trader"],
            as_index=False,
        ).agg(total_buy=("buy", "sum"), total_sell=("sell", "sum"))
        agg["net"] = agg["total_buy"] - agg["total_sell"]

        t1 = time.time()
        ok = save_to_db(agg, "chip_broker", chunksize=5000)
        logger.info(
            f"[券商分點] {len(agg)} 筆聚合資料寫入"
            f"{'成功' if ok else '失敗'} (耗時 {_elapsed(t0)})"
        )
        return ok

    # ------------------------------------------------------------------
    # 含息報酬指數
    # ------------------------------------------------------------------

    def _fetch_total_return_index(self, date_str):
        """取得含息報酬指數（TAIEX）。回傳 bool。"""
        t0 = time.time()
        logger.info(f"[含息報酬指數] 查詢 {date_str} ...")

        try:
            def _call():
                return self.fm_loader.taiwan_stock_total_return_index(
                    index_id="TAIEX", start_date=date_str, end_date=date_str
                )

            df = self.limiter.call_with_retry(_call)
        except Exception as e:
            etype = type(e).__name__
            logger.error(
                f"[含息報酬指數] API 異常: {etype}: {e} (耗時 {_elapsed(t0)})"
            )
            self.limiter.wait()
            return False

        if df is None or df.empty:
            status = "None" if df is None else "空 DataFrame"
            logger.info(f"[含息報酬指數] API 回傳 {status} (耗時 {_elapsed(t0)})")
            self.limiter.wait()
            return False

        logger.info(
            f"[含息報酬指數] API 回傳 {len(df)} 筆, "
            f"欄位: {list(df.columns)} "
            f"(耗時 {_elapsed(t0)})"
        )

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.date

        t1 = time.time()
        ok = save_to_db(df, "total_return_index")
        row_count = len(df) if ok else 0
        logger.info(
            f"[含息報酬指數] DB 寫入 {'成功' if ok else '失敗'}: {row_count} 筆 "
            f"(耗時 {_elapsed(t1)})"
        )
        self.limiter.wait()
        return ok


# ============================================================================
# Helpers
# ============================================================================

def _elapsed(t0: float) -> str:
    """回傳自 t0 以來的經過時間字串，如 '1.23s'。"""
    return f"{time.time() - t0:.2f}s"


def _weekday_name(d: date) -> str:
    """回傳中文星期名稱。"""
    names = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
    return names[d.weekday()]


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
