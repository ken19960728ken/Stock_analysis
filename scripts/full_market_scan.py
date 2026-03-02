#!/usr/bin/env python3
"""
全市場策略完整掃描 v4 — 本地快取 + 斷點續傳版本

核心改進（相較於 v3）：
- 本地 Parquet 快取：每批次資料存到本地，中斷後可續傳
- 主動式連線回收：每 3 批次關閉並重建連線，避免 Supabase idle 斷線
- 長冷卻期：批次間 10s 冷卻 + 錯誤後 60s 等待
- 多層容錯：批次失敗→逐支重試→跳過

用法:
    uv run python scripts/full_market_scan.py
    uv run python scripts/full_market_scan.py --years 3
    uv run python scripts/full_market_scan.py --strategies "MA 交叉" "MACD 訊號"
    uv run python scripts/full_market_scan.py --clear-cache   # 清除快取重新載入
"""

import argparse
import gc
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
from dotenv import load_dotenv

# 確保專案根目錄在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analysis.strategies import STRATEGY_MAP
from analysis.utils.backtester import Backtester
from core.constants import RISK_FREE_RATE, TRADING_DAYS_PER_YEAR
from core.logger import setup_logger

logger = setup_logger("full_scan")

SCAN_DIR = PROJECT_ROOT / "reports" / f"full_scan_{datetime.now().strftime('%Y%m%d')}"
CACHE_DIR = PROJECT_ROOT / "data_cache"
STRATEGIES = list(STRATEGY_MAP.keys())

# 策略所需補充資料（與 strategy_report.py / 3_策略回測.py 一致）
STRATEGY_DATA_NEEDS = {
    "法人跟單": ["chip_institutional"],
    "融資融券訊號": ["chip_margin"],
    "股權集中度": ["chip_holding_pct"],
    "財報三率": ["financial_reports"],
    "自由現金流": ["financial_reports", "market_value"],
    "價值投資": ["stock_per", "month_revenue"],
    "多因子綜合": ["chip_institutional", "stock_per"],
    "事件驅動": ["dividend_history"],
    "趨勢過濾MA": [],
    "多策略動態組合": ["chip_institutional", "stock_per", "month_revenue"],
}

# 合法表名白名單（防 SQL 注入）
VALID_TABLES = frozenset({
    "daily_price", "chip_institutional", "chip_margin", "chip_holding_pct",
    "financial_reports", "market_value", "stock_per", "month_revenue",
    "dividend_history",
})

BATCH_SIZE = 20          # 每批 20 支股票（~113s/batch）
BATCH_SIZE_SMALL = 10    # chip_holding_pct 每支股票行數多，用較小批次
MAX_RETRIES = 5          # 單批次最大重試次數
BATCH_COOLDOWN = 3       # 批次間冷卻秒數
ERROR_COOLDOWN = 15      # 錯誤後冷卻秒數

# ===================================================================
# psycopg2 直接連線（不用 SQLAlchemy）
# ===================================================================
# Supabase 提供兩種連線:
#   - Transaction Pooler (port 6543): 有 60 秒硬限制，不適合批量載入
#   - Session Pooler (port 5432): 無時間限制，適合長查詢
# 此腳本使用 Session Pooler + 每批獨立連線，確保穩定

_DSN = None


def _get_dsn() -> str:
    """取得 psycopg2 DSN（Session Pooler, port 5432）"""
    global _DSN
    if _DSN is not None:
        return _DSN

    load_dotenv()
    url = os.getenv("SUPABASE_URL")
    if not url:
        raise RuntimeError("找不到 SUPABASE_URL，請檢查 .env 檔案")

    # SQLAlchemy 格式 → psycopg2 格式
    dsn = url.replace("postgresql+psycopg2://", "postgresql://")

    # Transaction Pooler (6543) → Session Pooler (5432)
    if ":6543/" in dsn:
        dsn = dsn.replace(":6543/", ":5432/")
        logger.info("切換至 Session Pooler (port 5432) 以避免 60s timeout")

    _DSN = dsn
    return _DSN


def _fresh_conn():
    """建立全新的 psycopg2 連線（每次查詢用完就關閉）"""
    return psycopg2.connect(
        _get_dsn(),
        connect_timeout=30,
        options="-c statement_timeout=300000",  # 5 分鐘查詢超時
        keepalives=1,
        keepalives_idle=15,
        keepalives_interval=5,
        keepalives_count=3,
    )


QUERY_TIMEOUT = 180  # 硬性客戶端超時：3 分鐘


def _query_with_timeout(sql: str, params: tuple = ()) -> tuple[list, list]:
    """
    用全新 psycopg2 連線執行查詢，帶 3 分鐘硬性超時。

    使用 threading.Timer + conn.cancel() 確保查詢不會無限掛死。
    如果 cancel 失敗，直接關閉連線強制中斷。
    """
    conn = _fresh_conn()
    timed_out = [False]

    def kill_connection():
        timed_out[0] = True
        try:
            conn.cancel()
        except Exception:
            pass

    timer = threading.Timer(QUERY_TIMEOUT, kill_connection)
    timer.daemon = True
    timer.start()

    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        col_names = [desc[0] for desc in cur.description] if cur.description else []
        cur.close()
        conn.close()
        return rows, col_names
    except Exception as e:
        if timed_out[0]:
            try:
                conn.close()
            except Exception:
                pass
            raise TimeoutError(f"查詢超時 ({QUERY_TIMEOUT}s)")
        try:
            conn.close()
        except Exception:
            pass
        raise
    finally:
        timer.cancel()


def _query_with_retry(sql: str, params: tuple = (), max_retries: int = MAX_RETRIES) -> tuple[list, list]:
    """用全新連線執行查詢，失敗自動重試（帶硬性超時保護）"""
    for attempt in range(1, max_retries + 1):
        try:
            return _query_with_timeout(sql, params)
        except Exception as e:
            err_msg = str(e).lower()
            is_transient = any(kw in err_msg for kw in [
                "ssl", "eof", "connection", "timeout", "broken pipe",
                "server closed", "operational", "insufficient",
                "synchronization", "lost", "reset by peer",
                "cancel",
            ])
            if is_transient and attempt < max_retries:
                wait = ERROR_COOLDOWN * attempt
                logger.warning(
                    f"查詢失敗 (attempt {attempt}/{max_retries}): "
                    f"{type(e).__name__}"
                )
                time.sleep(wait)
            else:
                raise
    return [], []


# ===================================================================
# 本地 Parquet 快取
# ===================================================================

def _cache_path(table: str, batch_num: int) -> Path:
    """回傳批次快取檔案路徑"""
    return CACHE_DIR / table / f"batch_{batch_num:04d}.parquet"


def _load_from_cache(table: str, num_batches: int) -> dict[str, pd.DataFrame]:
    """從本地 Parquet 快取載入已完成的批次，回傳 {stock_id: DataFrame}"""
    result_dict: dict[str, pd.DataFrame] = {}
    cached_batches = 0
    total_rows = 0

    for i in range(1, num_batches + 1):
        path = _cache_path(table, i)
        if path.exists():
            try:
                df = pd.read_parquet(path)
                if "date" in df.columns:
                    df["date"] = pd.to_datetime(df["date"])
                for sid, group in df.groupby("stock_id"):
                    result_dict[str(sid)] = group.reset_index(drop=True)
                total_rows += len(df)
                cached_batches += 1
            except Exception as e:
                logger.warning(f"  快取讀取失敗 {path}: {e}")
                path.unlink(missing_ok=True)

    if cached_batches > 0:
        print(
            f"    ✓ 從快取載入 {cached_batches}/{num_batches} 批, "
            f"{len(result_dict)} 支, {total_rows:,} rows"
        )
    return result_dict


def _save_batch_cache(table: str, batch_num: int, df: pd.DataFrame):
    """儲存單批次資料到本地 Parquet"""
    path = _cache_path(table, batch_num)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_parquet(path, index=False)
    except Exception as e:
        logger.warning(f"  快取寫入失敗 {path}: {e}")


# ===================================================================
# 批次資料載入（含快取 + 主動回收 + 長冷卻）
# ===================================================================

def _query_one_batch(table: str, batch: list[str], start_date: str) -> pd.DataFrame | None:
    """用全新 psycopg2 連線查詢一批股票資料"""
    placeholders = ", ".join(["%s"] * len(batch))
    sql = (
        f"SELECT * FROM {table} "
        f"WHERE stock_id IN ({placeholders}) "
        f"AND date >= %s "
        f"ORDER BY stock_id, date"
    )
    params = tuple(batch) + (start_date,)

    rows, col_names = _query_with_retry(sql, params)

    if rows:
        df = pd.DataFrame(rows, columns=col_names)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    return None


def batch_load_table(
    table: str, stock_ids: list[str],
    start_date: str, batch_size: int = BATCH_SIZE,
) -> dict[str, pd.DataFrame]:
    """
    批次從 DB 載入整張表的資料，回傳 {stock_id: DataFrame}。

    特性:
    - 本地 Parquet 快取：已載入的批次不重複查詢
    - 每批獨立 psycopg2 連線：用完即關，不留殭屍連線
    - 自動重試 + 逐支降級
    """
    if table not in VALID_TABLES:
        raise ValueError(f"非法資料表: {table}")

    num_batches = (len(stock_ids) + batch_size - 1) // batch_size
    t0 = time.time()

    # 先從快取載入
    result_dict = _load_from_cache(table, num_batches)
    total_rows = sum(len(df) for df in result_dict.values())

    # 找出需要下載的批次
    batches_to_load = []
    for i in range(num_batches):
        batch_num = i + 1
        if not _cache_path(table, batch_num).exists():
            batches_to_load.append((batch_num, i * batch_size))

    if not batches_to_load:
        elapsed = time.time() - t0
        print(f"  ✓ {table}: 全部從快取載入 ({len(result_dict)} 支, {total_rows:,} rows, {elapsed:.0f}s)")
        return result_dict

    print(f"    需下載 {len(batches_to_load)}/{num_batches} 批...")
    failed_batches = 0

    for task_idx, (batch_num, start_idx) in enumerate(batches_to_load):
        batch = stock_ids[start_idx:start_idx + batch_size]

        # 嘗試載入此批次
        success = False
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                df = _query_one_batch(table, batch, start_date)
                if df is not None:
                    _save_batch_cache(table, batch_num, df)
                    for sid, group in df.groupby("stock_id"):
                        result_dict[str(sid)] = group.reset_index(drop=True)
                    total_rows += len(df)
                else:
                    _save_batch_cache(table, batch_num, pd.DataFrame())
                success = True
                break

            except Exception as e:
                if attempt < MAX_RETRIES:
                    wait = ERROR_COOLDOWN * attempt
                    logger.warning(
                        f"  {table} batch {batch_num} 失敗 "
                        f"(attempt {attempt}/{MAX_RETRIES}): "
                        f"{type(e).__name__}"
                    )
                    print(
                        f"    ⚠️ batch {batch_num} 錯誤 "
                        f"(retry {attempt}/{MAX_RETRIES})，等待 {wait}s..."
                    )
                    time.sleep(wait)
                else:
                    logger.error(
                        f"  {table} batch {batch_num} 永久失敗: {e}"
                    )
                    break

        if not success:
            failed_batches += 1
            print(f"    🔄 batch {batch_num} 改為逐支載入 ({len(batch)} 支)...")
            salvaged = _salvage_individual(
                table, batch, start_date, batch_num, result_dict
            )
            total_rows += salvaged

        # 進度報告
        done = task_idx + 1
        pct = done / len(batches_to_load) * 100
        elapsed = time.time() - t0
        eta = elapsed / done * (len(batches_to_load) - done) if done > 0 else 0
        print(
            f"    [{done}/{len(batches_to_load)}] "
            f"{pct:.0f}% | {len(result_dict)} 支 | "
            f"{total_rows:,} rows | {elapsed:.0f}s | ETA {eta:.0f}s"
        )

        # 批次間冷卻
        if task_idx < len(batches_to_load) - 1:
            time.sleep(BATCH_COOLDOWN)

    elapsed = time.time() - t0
    msg = f"{table}: {len(result_dict)} 支, {total_rows:,} rows, {elapsed:.0f}s"
    if failed_batches > 0:
        msg += f" ({failed_batches} 批失敗)"
    print(f"  ✓ {msg}")
    return result_dict


def _salvage_individual(
    table: str, stock_ids: list[str],
    start_date: str, batch_num: int,
    result_dict: dict[str, pd.DataFrame],
) -> int:
    """對失敗批次中的股票逐支嘗試載入（搶救部分資料）"""
    salvaged_rows = 0
    salvaged_dfs = []

    for sid in stock_ids:
        try:
            time.sleep(3)
            df = _query_one_batch(table, [sid], start_date)
            if df is not None and not df.empty:
                result_dict[str(sid)] = df.reset_index(drop=True)
                salvaged_dfs.append(df)
                salvaged_rows += len(df)
        except Exception:
            time.sleep(10)

    if salvaged_dfs:
        combined = pd.concat(salvaged_dfs, ignore_index=True)
        _save_batch_cache(table, batch_num, combined)
        print(f"      搶救成功: {len(salvaged_dfs)}/{len(stock_ids)} 支, {salvaged_rows} rows")
    else:
        _save_batch_cache(table, batch_num, pd.DataFrame())

    return salvaged_rows


def load_all_stock_ids() -> list[str]:
    """載入所有股票代碼"""
    sql = (
        'SELECT "商品代號" FROM twstock_code '
        "WHERE \"CFICode\" = 'ESVUFR' OR \"商品類型\" = 'ETF' "
        'ORDER BY "商品代號"'
    )
    rows, _ = _query_with_retry(sql)
    return [r[0] for r in rows]


def load_all_stock_names() -> dict[str, str]:
    """載入所有股票名稱"""
    sql = 'SELECT "商品代號", "商品名稱" FROM twstock_code'
    rows, _ = _query_with_retry(sql)
    return {str(r[0]): r[1] for r in rows}


# ===================================================================
# 記憶體內資料合併
# ===================================================================

def enrich_from_memory(
    df: pd.DataFrame, stock_id: str, strategy_name: str,
    supp_cache: dict[str, dict[str, pd.DataFrame]],
) -> pd.DataFrame:
    """從預載入的記憶體資料合併補充資料（邏輯與 strategy_report.py 一致）"""
    needs = STRATEGY_DATA_NEEDS.get(strategy_name, [])
    if not needs:
        return df

    df = df.sort_values("date").copy()

    for table in needs:
        table_data = supp_cache.get(table, {})
        extra = table_data.get(stock_id)
        if extra is None or extra.empty:
            continue
        extra = extra.copy()

        try:
            if table == "chip_institutional":
                buy_cols = [c for c in extra.columns if c.endswith("_buy")]
                sell_cols = [c for c in extra.columns if c.endswith("_sell")]
                if buy_cols and sell_cols:
                    extra["institutional_net_buy"] = (
                        extra[buy_cols].sum(axis=1) - extra[sell_cols].sum(axis=1)
                    )
                keep = ["date", "institutional_net_buy"]
                extra = extra[[c for c in keep if c in extra.columns]]
                df = df.merge(extra, on="date", how="left")

            elif table == "chip_margin":
                extra = extra.drop(columns=["stock_id"], errors="ignore")
                df = df.merge(extra, on="date", how="left")

            elif table == "chip_holding_pct":
                if "people" in extra.columns and "percent" in extra.columns:
                    agg = extra.groupby("date").agg(
                        shareholder_count=("people", "sum"),
                        holding_percentage=("percent", "sum"),
                    ).reset_index().sort_values("date")
                    df = pd.merge_asof(df, agg, on="date", direction="backward")

            elif table == "financial_reports":
                if "type" in extra.columns:
                    pivoted = extra.pivot_table(
                        index="date", columns="type",
                        values="value", aggfunc="first",
                    ).reset_index()
                    pivoted.columns.name = None
                    pivoted = pivoted.sort_values("date")
                    df = pd.merge_asof(
                        df, pivoted, on="date", direction="backward"
                    )

            elif table == "market_value":
                mv_cols = ["date"] + [
                    c for c in extra.columns if c not in ("date", "stock_id")
                ]
                extra = extra[mv_cols].sort_values("date")
                df = pd.merge_asof(df, extra, on="date", direction="backward")

            elif table == "stock_per":
                extra = extra.drop(
                    columns=["stock_id"], errors="ignore"
                ).sort_values("date")
                df = pd.merge_asof(df, extra, on="date", direction="backward")

            elif table == "month_revenue":
                extra = extra.drop(
                    columns=["stock_id"], errors="ignore"
                ).sort_values("date")
                df = pd.merge_asof(df, extra, on="date", direction="backward")

            elif table == "dividend_history":
                extra = extra.drop(
                    columns=["stock_id"], errors="ignore"
                ).sort_values("date")
                if "dividend" not in extra.columns:
                    for col in [
                        "cash_dividend", "stock_dividend", "total_dividend"
                    ]:
                        if col in extra.columns:
                            extra = extra.rename(columns={col: "dividend"})
                            break
                if "dividend" in extra.columns:
                    extra = extra[["date", "dividend"]]
                    df = df.merge(extra, on="date", how="left")
                    df["dividend"] = df["dividend"].fillna(0)

        except Exception as e:
            logger.debug(
                f"  {stock_id} enrich {table} 失敗: {type(e).__name__}: {e}"
            )

    return df


# ===================================================================
# 0050 基準
# ===================================================================

def calc_benchmark(
    daily_0050: pd.DataFrame | None,
    capital: float = 1_000_000,
) -> dict | None:
    """從預載入的 0050 日K資料計算買入持有基準"""
    if daily_0050 is None or len(daily_0050) < 2:
        return None

    df = daily_0050.sort_values("date")
    commission_rate = 0.001425
    first_close = df.iloc[0]["close"]
    shares = int(capital / (first_close * (1 + commission_rate)) / 1000) * 1000
    if shares <= 0:
        return None
    buy_cost = shares * first_close * (1 + commission_rate)
    cash = capital - buy_cost

    equity = cash + shares * df["close"].values
    dates = pd.to_datetime(df["date"].values)
    equity_curve = pd.Series(equity, index=dates)

    total_return = equity_curve.iloc[-1] / capital - 1
    days = (dates[-1] - dates[0]).days
    annual_return = (1 + total_return) ** (365 / days) - 1 if days > 0 else 0.0

    returns = equity_curve.pct_change().dropna()
    rf = RISK_FREE_RATE
    if len(returns) > 1 and returns.std() > 1e-12:
        sharpe = (
            (returns.mean() - rf / TRADING_DAYS_PER_YEAR)
            / returns.std()
            * np.sqrt(TRADING_DAYS_PER_YEAR)
        )
    else:
        sharpe = 0.0

    peak = equity_curve.cummax()
    dd = (equity_curve - peak) / peak

    return {
        "total_return": total_return,
        "annual_return": annual_return,
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown": dd.min(),
    }


# ===================================================================
# 回測
# ===================================================================

def backtest_one_stock(
    stock_id: str,
    daily: pd.DataFrame,
    strategy_name: str,
    strategy,
    supp_cache: dict,
    capital: float = 1_000_000,
) -> dict | None:
    """對單支股票做回測（全部從記憶體讀取，無 DB 存取）"""
    try:
        if len(daily) < 30:
            return None

        close_std = daily["close"].std()
        if close_std is None or np.isnan(close_std) or close_std < 1e-8:
            return None

        df = enrich_from_memory(daily, stock_id, strategy_name, supp_cache)
        result = Backtester(strategy, capital=capital).run(df)

        return {
            "stock_id": stock_id,
            "總報酬率(%)": round(result.total_return * 100, 2),
            "年化報酬(%)": round(result.annual_return * 100, 2),
            "Sharpe": result.sharpe_ratio,
            "最大回撤(%)": round(result.max_drawdown * 100, 2),
            "勝率(%)": round(result.win_rate * 100, 2),
            "交易次數": result.trade_count,
        }
    except (KeyError, ZeroDivisionError, ValueError) as e:
        logger.debug(f"  {stock_id} 跳過: {type(e).__name__}: {e}")
        return None
    except Exception as e:
        logger.warning(f"  {stock_id} 異常: {type(e).__name__}: {e}")
        return None


def run_strategy(
    strategy_name: str,
    stock_ids: list[str],
    daily_data: dict[str, pd.DataFrame],
    stock_names: dict[str, str],
    supp_cache: dict,
    capital: float = 1_000_000,
) -> list[dict]:
    """對所有股票執行單一策略的回測"""
    strategy = STRATEGY_MAP[strategy_name]()
    results: list[dict] = []
    skipped = 0
    t0 = time.time()

    for idx, sid in enumerate(stock_ids):
        daily = daily_data.get(sid)
        if daily is None or daily.empty:
            skipped += 1
            continue

        row = backtest_one_stock(
            sid, daily, strategy_name, strategy, supp_cache, capital
        )
        if row is not None:
            row["name"] = stock_names.get(sid, "")
            results.append(row)

        # 進度報告
        if (idx + 1) % 500 == 0:
            elapsed = time.time() - t0
            rate = (idx + 1) / elapsed
            remaining = (len(stock_ids) - idx - 1) / rate if rate > 0 else 0
            traded = sum(1 for r in results if r["交易次數"] > 0)
            print(
                f"    {idx+1}/{len(stock_ids)} "
                f"({traded} traded, {elapsed:.0f}s, ~{remaining:.0f}s remaining)"
            )

    elapsed = time.time() - t0
    traded = sum(1 for r in results if r["交易次數"] > 0)
    print(
        f"    完成: {len(results)} 有結果 / {traded} 有交易 / "
        f"{skipped} 無資料 / {elapsed:.0f}s"
    )
    return results


# ===================================================================
# 報告生成
# ===================================================================

def generate_report(
    all_results: dict[str, list[dict]],
    benchmark: dict | None,
    scan_times: dict[str, float],
    total_stocks: int,
    start_date: str,
    strategies_run: list[str],
) -> Path:
    """生成完整的 .md 彙整報告"""
    report_path = SCAN_DIR / "full_scan_report.md"
    lines: list[str] = []

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    total_time = sum(scan_times.values())

    lines.append("# 全市場策略掃描彙整報告")
    lines.append("")
    lines.append(f"**掃描時間**: {now}")
    lines.append(f"**回測期間**: {start_date} ~ {datetime.now().strftime('%Y-%m-%d')}")
    lines.append(f"**策略數量**: {len(strategies_run)} 個")
    lines.append(f"**掃描股票數**: ~{total_stocks} 支")
    lines.append(f"**總執行時間**: {total_time/60:.1f} 分鐘")
    lines.append("")

    # === 0050 基準 ===
    lines.append("---")
    lines.append("")
    lines.append("## 0050 買入持有基準")
    lines.append("")
    if benchmark:
        lines.append("| 指標 | 數值 |")
        lines.append("|------|------|")
        lines.append(f"| 總報酬率 | {benchmark['total_return']*100:.2f}% |")
        lines.append(f"| 年化報酬 | {benchmark['annual_return']*100:.2f}% |")
        lines.append(f"| Sharpe Ratio | {benchmark['sharpe_ratio']:.2f} |")
        lines.append(f"| 最大回撤 | {benchmark['max_drawdown']*100:.2f}% |")
    else:
        lines.append("*無法取得 0050 基準資料*")
    lines.append("")

    # === 執行摘要 ===
    lines.append("---")
    lines.append("")
    lines.append("## 執行摘要")
    lines.append("")
    lines.append("| # | 策略 | 耗時(秒) | 有結果 | 有交易 | 狀態 |")
    lines.append("|---|------|---------|--------|--------|------|")
    for i, strategy in enumerate(strategies_run, 1):
        results = all_results.get(strategy, [])
        elapsed = scan_times.get(strategy, 0)
        traded = sum(1 for r in results if r.get("交易次數", 0) > 0)
        status = "✅" if results else "⚠️"
        lines.append(
            f"| {i} | {strategy} | {elapsed:.0f} | "
            f"{len(results)} | {traded} | {status} |"
        )
    lines.append("")

    # === 策略綜合比較 ===
    lines.append("---")
    lines.append("")
    lines.append("## 策略綜合比較")
    lines.append("")

    summary_rows = []
    for strategy in strategies_run:
        results = all_results.get(strategy, [])
        if not results:
            continue
        df = pd.DataFrame(results)
        traded = df[df["交易次數"] > 0]

        bench_annual = (
            benchmark["annual_return"] * 100 if benchmark else 999
        )
        beat_count = (
            len(traded[traded["年化報酬(%)"] > bench_annual])
            if not traded.empty
            else 0
        )

        summary_rows.append({
            "策略": strategy,
            "有交易股數": len(traded),
            "平均年化(%)": (
                round(traded["年化報酬(%)"].mean(), 2)
                if not traded.empty else 0
            ),
            "中位年化(%)": (
                round(traded["年化報酬(%)"].median(), 2)
                if not traded.empty else 0
            ),
            "平均Sharpe": (
                round(traded["Sharpe"].mean(), 2)
                if not traded.empty else 0
            ),
            "平均勝率(%)": (
                round(traded["勝率(%)"].mean(), 1)
                if not traded.empty else 0
            ),
            "勝0050比例(%)": (
                round(beat_count / len(traded) * 100, 1)
                if len(traded) > 0 else 0
            ),
            "平均交易次數": (
                round(traded["交易次數"].mean(), 1)
                if not traded.empty else 0
            ),
        })

    if summary_rows:
        summary_df = pd.DataFrame(summary_rows).sort_values(
            "平均年化(%)", ascending=False
        )

        lines.append(
            "| 排名 | 策略 | 有交易股數 | 平均年化(%) | 中位年化(%) | "
            "平均Sharpe | 平均勝率(%) | 勝0050(%) | 平均交易次數 |"
        )
        lines.append(
            "|------|------|-----------|-----------|-----------|"
            "----------|-----------|----------|----------|"
        )
        for rank, (_, row) in enumerate(summary_df.iterrows(), 1):
            lines.append(
                f"| {rank} | {row['策略']} | {row['有交易股數']} | "
                f"{row['平均年化(%)']:+.2f} | {row['中位年化(%)']:+.2f} | "
                f"{row['平均Sharpe']:.2f} | {row['平均勝率(%)']:.1f} | "
                f"{row['勝0050比例(%)']:.1f} | {row['平均交易次數']:.1f} |"
            )
        lines.append("")

    # === 各策略 Top 10 + Bottom 5 ===
    lines.append("---")
    lines.append("")
    lines.append("## 各策略個股表現")
    lines.append("")

    for strategy in strategies_run:
        results = all_results.get(strategy, [])
        lines.append(f"### {strategy}")
        lines.append("")

        if not results:
            lines.append("*無資料或執行失敗*")
            lines.append("")
            continue

        df = pd.DataFrame(results)
        traded = df[df["交易次數"] > 0]

        lines.append(
            f"掃描: {len(df)} 支 | 有交易: {len(traded)} 支 | "
            f"無交易: {len(df) - len(traded)} 支"
        )
        lines.append("")

        if traded.empty:
            lines.append("*所有股票均無產生交易訊號*")
            lines.append("")
            continue

        # Top 10
        n_top = min(10, len(traded))
        top10 = traded.nlargest(n_top, "年化報酬(%)")
        lines.append(f"**表現最佳 Top {n_top}:**")
        lines.append("")
        lines.append(
            "| 排名 | 代號 | 名稱 | 年化報酬(%) | Sharpe | "
            "最大回撤(%) | 勝率(%) | 交易次數 |"
        )
        lines.append(
            "|------|------|------|-----------|--------|"
            "----------|---------|---------|"
        )
        for rank, (_, row) in enumerate(top10.iterrows(), 1):
            lines.append(
                f"| {rank} | {row['stock_id']} | {row['name']} | "
                f"{row['年化報酬(%)']:+.2f} | {row['Sharpe']:.2f} | "
                f"{row['最大回撤(%)']:.2f} | {row['勝率(%)']:.1f} | "
                f"{int(row['交易次數'])} |"
            )
        lines.append("")

        # Bottom 5
        n_bottom = min(5, len(traded))
        bottom5 = traded.nsmallest(n_bottom, "年化報酬(%)")
        lines.append(f"**表現最差 Bottom {n_bottom}:**")
        lines.append("")
        lines.append(
            "| 排名 | 代號 | 名稱 | 年化報酬(%) | Sharpe | "
            "最大回撤(%) | 勝率(%) | 交易次數 |"
        )
        lines.append(
            "|------|------|------|-----------|--------|"
            "----------|---------|---------|"
        )
        for rank, (_, row) in enumerate(bottom5.iterrows(), 1):
            lines.append(
                f"| {rank} | {row['stock_id']} | {row['name']} | "
                f"{row['年化報酬(%)']:+.2f} | {row['Sharpe']:.2f} | "
                f"{row['最大回撤(%)']:.2f} | {row['勝率(%)']:.1f} | "
                f"{int(row['交易次數'])} |"
            )
        lines.append("")

    # === 關鍵發現 ===
    lines.append("---")
    lines.append("")
    lines.append("## 關鍵發現與分析")
    lines.append("")

    if summary_rows:
        sorted_rows = sorted(
            summary_rows, key=lambda x: x["平均年化(%)"], reverse=True
        )

        best = sorted_rows[0]
        lines.append("### 最佳策略")
        lines.append(
            f"- **{best['策略']}**: 平均年化 {best['平均年化(%)']:+.2f}%, "
            f"Sharpe {best['平均Sharpe']:.2f}"
        )
        lines.append("")

        worst = sorted_rows[-1]
        lines.append("### 最差策略")
        lines.append(
            f"- **{worst['策略']}**: 平均年化 {worst['平均年化(%)']:+.2f}%, "
            f"Sharpe {worst['平均Sharpe']:.2f}"
        )
        lines.append("")

        best_sharpe = max(summary_rows, key=lambda x: x["平均Sharpe"])
        lines.append("### 風險調整最佳")
        lines.append(
            f"- **{best_sharpe['策略']}**: Sharpe {best_sharpe['平均Sharpe']:.2f}, "
            f"年化 {best_sharpe['平均年化(%)']:+.2f}%"
        )
        lines.append("")

        best_beat = max(summary_rows, key=lambda x: x["勝0050比例(%)"])
        lines.append("### 勝 0050 比例最高")
        lines.append(
            f"- **{best_beat['策略']}**: "
            f"{best_beat['勝0050比例(%)']:.1f}% 個股打敗 0050"
        )
        lines.append("")

        if benchmark:
            bench_annual = benchmark["annual_return"] * 100
            beaten = [
                r for r in sorted_rows if r["平均年化(%)"] > bench_annual
            ]
            if beaten:
                lines.append("### 平均年化打敗 0050 的策略")
                for b in beaten:
                    lines.append(
                        f"- {b['策略']}: {b['平均年化(%)']:+.2f}% "
                        f"(0050: {bench_annual:+.2f}%)"
                    )
            else:
                lines.append("### 注意")
                lines.append(
                    f"- 沒有任何策略的「平均」年化報酬打敗 0050 "
                    f"({bench_annual:+.2f}%)"
                )
                lines.append(
                    "- 在多頭市場中，買入持有通常優於主動交易策略"
                )
            lines.append("")

    # === 改進說明 ===
    lines.append("---")
    lines.append("")
    lines.append("## 本次掃描改進說明")
    lines.append("")
    lines.append("相較於上一次掃描（v1），本次掃描包含以下關鍵修正：")
    lines.append("")
    lines.append(
        "1. **Look-Ahead Bias 修正**: "
        "訊號延遲一日執行（signal shift +1），消除前視偏差"
    )
    lines.append(
        "2. **批次資料預載入**: "
        "一次性載入所有資料到記憶體，DB 查詢從 ~37,000 降至 ~50"
    )
    lines.append(
        "3. **股權集中度修正**: "
        "改用 chip_holding_pct 表，新增 holding_percentage 欄位"
    )
    lines.append(
        "4. **stock_per 合併修正**: "
        "改用 merge_asof 前向填充，消除大量 NaN"
    )
    lines.append(
        "5. **Strategy params 修正**: "
        "實例層級 params 副本，避免參數污染"
    )
    lines.append(
        "6. **事件驅動修正**: 避免除息事件訊號重疊衝突"
    )
    lines.append("7. **除零保護**: 低流動性股票自動跳過")
    lines.append("8. **新增策略**: 趨勢過濾MA、多策略動態組合")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        f"*報告生成時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*"
    )

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


# ===================================================================
# 主流程
# ===================================================================

def main():
    parser = argparse.ArgumentParser(
        description="全市場策略完整掃描 v4（本地快取 + 斷點續傳）"
    )
    parser.add_argument(
        "--years", type=int, default=2, help="回測年數（預設 2）"
    )
    parser.add_argument(
        "--strategies", nargs="+",
        help="指定策略（預設全部 18 個）"
    )
    parser.add_argument(
        "--capital", type=float, default=1_000_000, help="初始資金"
    )
    parser.add_argument(
        "--clear-cache", action="store_true",
        help="清除本地快取，強制重新載入"
    )
    args = parser.parse_args()

    # 清除快取
    if args.clear_cache:
        import shutil
        if CACHE_DIR.exists():
            shutil.rmtree(CACHE_DIR)
            print(f"已清除快取: {CACHE_DIR}")
        else:
            print("快取目錄不存在，無需清除")

    strategies_to_run = args.strategies or STRATEGIES

    # 驗證策略名稱
    for s in strategies_to_run:
        if s not in STRATEGY_MAP:
            print(f"未知策略: {s}")
            print(f"可用策略: {', '.join(STRATEGY_MAP.keys())}")
            return

    SCAN_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("  全市場策略完整掃描 v4（本地快取 + 斷點續傳）")
    print(f"  開始時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  策略數量: {len(strategies_to_run)}")
    print(f"  回測年數: {args.years}")
    print(f"  輸出目錄: {SCAN_DIR}")
    print("=" * 70)

    # 初始化 DSN（驗證連線能力）
    _get_dsn()

    end_date = datetime.now()
    start_date = (end_date - timedelta(days=365 * args.years)).strftime(
        "%Y-%m-%d"
    )

    # -------------------------------------------------------
    # Phase 1: 載入共用資料
    # -------------------------------------------------------
    print(f"\n{'='*60}")
    print("  Phase 1: 載入共用資料")
    print(f"{'='*60}")

    print("載入股票清單...")
    stock_ids = load_all_stock_ids()
    print(f"  共 {len(stock_ids)} 支股票")

    print("載入股票名稱...")
    stock_names = load_all_stock_names()
    print(f"  共 {len(stock_names)} 筆名稱")

    print(f"\n載入 daily_price (batch_size={BATCH_SIZE})...")
    daily_data = batch_load_table(
        "daily_price", stock_ids, start_date, BATCH_SIZE
    )

    # -------------------------------------------------------
    # Phase 2: 0050 基準
    # -------------------------------------------------------
    print(f"\n{'='*60}")
    print("  Phase 2: 0050 買入持有基準")
    print(f"{'='*60}")
    benchmark = calc_benchmark(daily_data.get("0050"), args.capital)
    if benchmark:
        print(f"  總報酬率:  {benchmark['total_return']*100:+.2f}%")
        print(f"  年化報酬:  {benchmark['annual_return']*100:+.2f}%")
        print(f"  Sharpe:    {benchmark['sharpe_ratio']:.2f}")
        print(f"  最大回撤:  {benchmark['max_drawdown']*100:.2f}%")
    else:
        print("  ⚠️ 無法計算 0050 基準")

    # -------------------------------------------------------
    # Phase 3: 載入補充資料
    # -------------------------------------------------------
    print(f"\n{'='*60}")
    print("  Phase 3: 載入補充資料")
    print(f"{'='*60}")

    all_needed_tables: set[str] = set()
    for strategy in strategies_to_run:
        for table in STRATEGY_DATA_NEEDS.get(strategy, []):
            all_needed_tables.add(table)

    supp_cache: dict[str, dict[str, pd.DataFrame]] = {}
    if all_needed_tables:
        print(f"需要載入: {', '.join(sorted(all_needed_tables))}")
        for table in sorted(all_needed_tables):
            bs = BATCH_SIZE_SMALL if table == "chip_holding_pct" else BATCH_SIZE
            print(f"\n載入 {table} (batch_size={bs})...")
            supp_cache[table] = batch_load_table(
                table, stock_ids, start_date, bs
            )
    else:
        print("所有策略僅需價格資料，無需補充資料。")

    print(f"\n所有資料載入完成。")
    gc.collect()

    # -------------------------------------------------------
    # Phase 4: 逐策略回測
    # -------------------------------------------------------
    print(f"\n{'='*60}")
    print("  Phase 4: 策略回測（純記憶體）")
    print(f"{'='*60}")

    all_results: dict[str, list[dict]] = {}
    scan_times: dict[str, float] = {}

    try:
        for idx, strategy_name in enumerate(strategies_to_run, 1):
            needs = STRATEGY_DATA_NEEDS.get(strategy_name, [])
            print(f"\n{'='*60}")
            print(f"  [{idx}/{len(strategies_to_run)}] {strategy_name}")
            print(f"  補充資料: {', '.join(needs) if needs else '(僅價格)'}")
            print(f"{'='*60}")

            t0 = time.time()
            results = run_strategy(
                strategy_name, stock_ids, daily_data, stock_names,
                supp_cache, args.capital,
            )
            elapsed = time.time() - t0

            all_results[strategy_name] = results
            scan_times[strategy_name] = elapsed

            traded = sum(1 for r in results if r.get("交易次數", 0) > 0)
            print(
                f"  ✅ {strategy_name}: {len(results)} 結果, "
                f"{traded} 有交易, {elapsed:.0f}s"
            )

            # 策略之間釋放記憶體碎片
            gc.collect()

    except KeyboardInterrupt:
        print("\n\n⚠️ 收到中斷信號，生成已完成策略的部分報告...")

    # -------------------------------------------------------
    # Phase 5: 生成報告
    # -------------------------------------------------------
    print(f"\n{'='*60}")
    print("  Phase 5: 生成報告")
    print(f"{'='*60}")

    report_path = generate_report(
        all_results, benchmark, scan_times, len(stock_ids),
        start_date, strategies_to_run,
    )

    # 同時儲存每個策略的 CSV
    for strategy_name, results in all_results.items():
        if results:
            df = pd.DataFrame(results)
            safe = strategy_name.replace(" ", "_")
            csv_path = SCAN_DIR / f"strategy_{safe}.csv"
            df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    total_time = sum(scan_times.values())
    completed = len(all_results)
    total = len(strategies_to_run)

    print(f"\n{'='*70}")
    print(f"  掃描完成！")
    print(f"  報告位置: {report_path}")
    print(f"  CSV 檔案: {SCAN_DIR}/")
    print(f"  完成策略: {completed}/{total}")
    print(f"  總執行時間: {total_time/60:.1f} 分鐘")
    print(f"  結束時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}")

    return str(report_path)


if __name__ == "__main__":
    main()
