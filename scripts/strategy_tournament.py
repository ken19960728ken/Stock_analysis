"""
策略淘汰賽 — OOS 驗證篩選 + 訊號衰減分析

自動對所有策略跑 oos_validation()，篩選出通過 OOS 驗證的策略進入 Paper Trading。

用法:
    uv run python scripts/strategy_tournament.py
    uv run python scripts/strategy_tournament.py --force
    uv run python main.py --strategy-tournament
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# 確保專案根目錄在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analysis.strategies import STRATEGY_MAP
from analysis.utils.data_loader import _compute_revenue_yoy
from analysis.utils.signal_analysis import oos_validation, signal_decay_report
from core.constants import apply_publication_delay
from core.db import get_engine, safe_read_sql, save_to_db
from core.logger import setup_logger

logger = setup_logger("strategy_tournament")

# ===================================================================
# 設定常數
# ===================================================================

# OOS 篩選門檻
OOS_SHARPE_MIN = 0.5
DECAY_RATE_MAX = 0.5

# 代表性股票數量
REPRESENTATIVE_COUNT = 20

# 回測資料長度（天）
LOOKBACK_DAYS = 3 * 365  # 3 年

# 快取有效期（天）
CACHE_VALID_DAYS = 30

# 各策略所需補充資料（與 daily_stock_picker 一致）
STRATEGY_DATA_NEEDS: dict[str, list[str]] = {
    "RSI 反轉": [],
    "價值投資": ["stock_per", "month_revenue"],
    "機器學習選股": [],
    "多因子綜合": ["chip_institutional", "stock_per"],
    "法人跟單": ["chip_institutional"],
    "趨勢過濾MA": [],
    "多策略動態組合": ["chip_institutional", "stock_per", "month_revenue"],
    "量價動能": [],
    "營收動能": ["month_revenue", "stock_per"],
    "波動率壓縮突破": [],
    "次產業輪動": ["month_revenue", "chip_institutional"],
    "當沖情緒反轉": ["day_trading"],
    "外資連續買超": ["chip_broker"],
    "散戶vs主力": ["day_trading", "chip_broker"],
    "官股護盤": ["chip_gov_bank"],
}

# 信號衰減分析用的 horizons
DECAY_HORIZONS = [5, 10, 20]


# ===================================================================
# 資料載入
# ===================================================================

def _load_table_chunked(
    table_name: str, start_date: str, end_date: str | None = None,
) -> pd.DataFrame:
    """分月查詢大表，避免 Supabase 2 分鐘 statement_timeout"""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d") if end_date else datetime.now()

    chunks: list[pd.DataFrame] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=44), end)
        sql = f"SELECT * FROM {table_name} WHERE date >= %(sd)s AND date <= %(ed)s"
        p = {"sd": cursor.strftime("%Y-%m-%d"), "ed": chunk_end.strftime("%Y-%m-%d")}
        df = safe_read_sql(sql, params=p, timeout_ms=300_000)
        if not df.empty:
            chunks.append(df)
        cursor = chunk_end + timedelta(days=1)

    return pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()


def _build_stock_cache(df: pd.DataFrame | None) -> dict[str, pd.DataFrame]:
    """依 stock_id 分組"""
    if df is None or df.empty:
        return {}
    return {
        sid: grp.reset_index(drop=True)
        for sid, grp in df.groupby("stock_id", sort=False)
    }


def _load_representative_stocks() -> list[str]:
    """選出代表性高流動性股票（跨產業，最多 REPRESENTATIVE_COUNT 支）

    策略：取近 60 日平均成交量最高的股票，每個產業最多 3 支，確保產業分散。
    """
    sql = """
    WITH recent_avg AS (
        SELECT stock_id, AVG(volume) AS avg_vol
        FROM daily_price
        WHERE date >= %(cutoff)s
        GROUP BY stock_id
        HAVING AVG(volume) > 500000
    ),
    with_sector AS (
        SELECT r.stock_id, r.avg_vol, COALESCE(i.sector, '其他') AS sector
        FROM recent_avg r
        LEFT JOIN industry_classification i ON r.stock_id = i.stock_id
    ),
    ranked AS (
        SELECT stock_id, avg_vol, sector,
               ROW_NUMBER() OVER (PARTITION BY sector ORDER BY avg_vol DESC) AS rn
        FROM with_sector
    )
    SELECT stock_id FROM ranked
    WHERE rn <= 3
    ORDER BY avg_vol DESC
    LIMIT %(limit)s
    """
    cutoff = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    df = safe_read_sql(sql, params={"cutoff": cutoff, "limit": REPRESENTATIVE_COUNT})
    if df.empty:
        logger.warning("無法從 DB 選出代表性股票，使用預設清單")
        return ["2330", "2317", "2454", "2412", "2882", "2881",
                "2891", "2303", "1301", "2308", "3711", "2002",
                "1303", "2886", "6505", "2892", "5880", "2207",
                "3037", "2345"]
    stocks = df["stock_id"].tolist()
    logger.info(f"選出 {len(stocks)} 支代表性股票")
    return stocks


def _load_tournament_data(
    stock_ids: list[str], start_date: str, end_date: str | None = None,
) -> dict[str, dict[str, pd.DataFrame]]:
    """載入所有代表性股票所需的資料

    Returns: {stock_id: {"price": df, "chip_institutional": df, ...}}
    """
    logger.info(f"載入 {len(stock_ids)} 支股票的回測資料 ({start_date} ~)")

    # 載入 daily_price
    price_all = _load_table_chunked("daily_price", start_date, end_date)
    price_cache = _build_stock_cache(price_all)

    # 載入各補充表
    needed_tables: set[str] = set()
    for needs in STRATEGY_DATA_NEEDS.values():
        needed_tables.update(needs)

    table_caches: dict[str, dict[str, pd.DataFrame]] = {}
    for table_name in needed_tables:
        if table_name == "month_revenue":
            # 月營收需要往前推 450 天（YoY 計算）
            rev_start = (
                datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=450)
            ).strftime("%Y-%m-%d")
            sql = "SELECT * FROM month_revenue WHERE date >= %(sd)s"
            p: dict = {"sd": rev_start}
            if end_date:
                sql += " AND date <= %(ed)s"
                p["ed"] = end_date
            rev_df = safe_read_sql(sql, params=p, timeout_ms=300_000)
            rev_df = _compute_revenue_yoy(rev_df)
            table_caches[table_name] = _build_stock_cache(rev_df)
        else:
            tbl_df = _load_table_chunked(table_name, start_date, end_date)
            table_caches[table_name] = _build_stock_cache(tbl_df)

    # 組裝成 {stock_id: {"price": df, table_name: df, ...}}
    result: dict[str, dict[str, pd.DataFrame]] = {}
    for sid in stock_ids:
        if sid not in price_cache:
            continue
        stock_data: dict[str, pd.DataFrame] = {"price": price_cache[sid]}
        for table_name in needed_tables:
            stock_data[table_name] = table_caches.get(table_name, {}).get(
                sid, pd.DataFrame()
            )
        result[sid] = stock_data

    logger.info(f"成功載入 {len(result)} 支股票的資料")
    return result


def _enrich_for_strategy(
    df: pd.DataFrame,
    stock_id: str,
    strategy_name: str,
    stock_data: dict[str, pd.DataFrame],
    ind_map: dict[str, dict] | None = None,
) -> pd.DataFrame:
    """根據策略需求合併補充資料"""
    needs = STRATEGY_DATA_NEEDS.get(strategy_name, [])
    if not needs:
        return df

    df = df.sort_values("date").copy()

    # 次產業輪動需要 sub_industry
    if strategy_name == "次產業輪動" and ind_map:
        info = ind_map.get(stock_id, {})
        df["sub_industry"] = info.get("sub_industry")

    for table in needs:
        extra = stock_data.get(table, pd.DataFrame())
        if extra.empty:
            continue

        # 快取的補充資料 date 為 object 字串，price df 已是 datetime64，
        # merge_asof 要求兩側 dtype 一致，否則拋 MergeError（會被靜默吞掉）。
        if "date" in extra.columns and not pd.api.types.is_datetime64_any_dtype(extra["date"]):
            extra = extra.copy()
            extra["date"] = pd.to_datetime(extra["date"])

        if table == "chip_institutional":
            extra = extra.copy()
            buy_cols = [c for c in extra.columns if c.endswith("_buy")]
            sell_cols = [c for c in extra.columns if c.endswith("_sell")]
            if buy_cols and sell_cols:
                extra["institutional_net_buy"] = (
                    extra[buy_cols].sum(axis=1) - extra[sell_cols].sum(axis=1)
                )
            keep_set = {"date", "institutional_net_buy"}
            for c in extra.columns:
                if c.endswith("_buy") or c.endswith("_sell"):
                    keep_set.add(c)
            extra = extra[[c for c in extra.columns if c in keep_set]]
            extra = extra.sort_values("date")
            extra = apply_publication_delay(extra, "chip_institutional")
            df = pd.merge_asof(df, extra, on="date", direction="backward")

        elif table == "stock_per":
            extra = extra.drop(columns=["stock_id"], errors="ignore").sort_values("date")
            extra = apply_publication_delay(extra, "stock_per")
            df = pd.merge_asof(df, extra, on="date", direction="backward")

        elif table == "month_revenue":
            extra = extra.drop(columns=["stock_id"], errors="ignore").sort_values("date")
            extra = apply_publication_delay(extra, "month_revenue")
            df = pd.merge_asof(df, extra, on="date", direction="backward")

        elif table in ("day_trading", "chip_broker", "chip_gov_bank"):
            extra = extra.drop(columns=["stock_id"], errors="ignore").sort_values("date")
            extra = apply_publication_delay(extra, table)
            df = pd.merge_asof(df, extra, on="date", direction="backward")

    return df


# ===================================================================
# 策略評估
# ===================================================================

def _evaluate_strategy(
    strategy_name: str,
    strategy_cls: type,
    all_stock_data: dict[str, dict[str, pd.DataFrame]],
    ind_map: dict[str, dict] | None = None,
) -> dict:
    """對單一策略跑所有代表性股票的 OOS 驗證 + 信號衰減

    Returns: {
        name, is_sharpe_avg, oos_sharpe_avg, decay_rate_avg, verdict,
        signal_decay_t5, signal_decay_t10, signal_decay_t20,
        stock_count, details
    }
    """
    strategy = strategy_cls()
    oos_results: list[dict] = []
    decay_summaries: list[pd.DataFrame] = []
    evaluated_count = 0

    for stock_id, stock_data in all_stock_data.items():
        price_df = stock_data.get("price", pd.DataFrame())
        if price_df.empty or len(price_df) < 200:
            continue

        # 確保 date 為 datetime
        if "date" in price_df.columns and not pd.api.types.is_datetime64_any_dtype(price_df["date"]):
            price_df = price_df.copy()
            price_df["date"] = pd.to_datetime(price_df["date"])

        try:
            enriched = _enrich_for_strategy(
                price_df, stock_id, strategy_name, stock_data, ind_map,
            )

            # OOS 驗證
            oos_result = oos_validation(strategy, enriched)
            oos_results.append(oos_result)

            # 信號衰減
            _, summary = signal_decay_report(strategy, enriched, horizons=DECAY_HORIZONS)
            if not summary.empty:
                decay_summaries.append(summary)

            evaluated_count += 1
        except Exception as e:
            logger.warning(f"  {strategy_name}/{stock_id} 評估失敗: {type(e).__name__}: {e}")

    if not oos_results:
        return {
            "name": strategy_name,
            "is_sharpe_avg": np.nan,
            "oos_sharpe_avg": np.nan,
            "decay_rate_avg": np.nan,
            "verdict": "no_data",
            "signal_decay_t5": np.nan,
            "signal_decay_t10": np.nan,
            "signal_decay_t20": np.nan,
            "stock_count": 0,
        }

    # 彙總 OOS 結果
    is_sharpes = [r["is_sharpe"] for r in oos_results if np.isfinite(r["is_sharpe"])]
    oos_sharpes = [r["oos_sharpe"] for r in oos_results if np.isfinite(r["oos_sharpe"])]
    decay_rates = [r["decay_rate"] for r in oos_results if np.isfinite(r["decay_rate"])]

    is_sharpe_avg = float(np.mean(is_sharpes)) if is_sharpes else np.nan
    oos_sharpe_avg = float(np.mean(oos_sharpes)) if oos_sharpes else np.nan
    decay_rate_avg = float(np.mean(decay_rates)) if decay_rates else np.nan

    # 綜合 verdict
    if np.isnan(decay_rate_avg):
        verdict = "no_data"
    elif decay_rate_avg < 0.2:
        verdict = "stable"
    elif decay_rate_avg < 0.5:
        verdict = "moderate"
    elif decay_rate_avg < 0.8:
        verdict = "severe"
    else:
        verdict = "overfitting"

    # 彙總信號衰減
    decay_by_horizon: dict[int, float] = {}
    if decay_summaries:
        combined = pd.concat(decay_summaries, ignore_index=True)
        for h in DECAY_HORIZONS:
            rows = combined[combined["horizon"] == h]
            vals = rows["mean_return"].dropna()
            decay_by_horizon[h] = float(vals.mean()) if len(vals) > 0 else np.nan

    return {
        "name": strategy_name,
        "is_sharpe_avg": is_sharpe_avg,
        "oos_sharpe_avg": oos_sharpe_avg,
        "decay_rate_avg": decay_rate_avg,
        "verdict": verdict,
        "signal_decay_t5": decay_by_horizon.get(5, np.nan),
        "signal_decay_t10": decay_by_horizon.get(10, np.nan),
        "signal_decay_t20": decay_by_horizon.get(20, np.nan),
        "stock_count": evaluated_count,
    }


# ===================================================================
# 快取 & 報告
# ===================================================================

def _should_rerun(force: bool = False) -> bool:
    """檢查是否需要重新跑淘汰賽"""
    if force:
        return True
    try:
        df = safe_read_sql(
            "SELECT MAX(run_date) AS last_run FROM strategy_tournament_results",
        )
        if df.empty or df["last_run"].iloc[0] is None:
            return True
        last_run = pd.to_datetime(df["last_run"].iloc[0])
        days_since = (datetime.now() - last_run).days
        if days_since >= CACHE_VALID_DAYS:
            logger.info(f"上次執行距今 {days_since} 天，需要重新跑")
            return True
        logger.info(f"上次執行距今 {days_since} 天（< {CACHE_VALID_DAYS}），使用快取結果")
        return False
    except Exception:
        return True


def _load_cached_results() -> dict:
    """載入最近一次的淘汰賽結果"""
    try:
        df = safe_read_sql(
            "SELECT * FROM strategy_tournament_results "
            "WHERE run_date = (SELECT MAX(run_date) FROM strategy_tournament_results)"
        )
        if df.empty:
            return {}
        approved = df[df["approved"] == True]["strategy_name"].tolist()  # noqa: E712
        return {
            "approved_strategies": approved,
            "full_ranking": df.to_dict("records"),
            "run_date": str(df["run_date"].iloc[0])[:10],
        }
    except Exception:
        return {}


def _save_results(results: list[dict], run_date: str) -> bool:
    """儲存淘汰賽結果到 DB"""
    rows = []
    for r in results:
        rows.append({
            "run_date": run_date,
            "strategy_name": r["name"],
            "is_sharpe_avg": r["is_sharpe_avg"],
            "oos_sharpe_avg": r["oos_sharpe_avg"],
            "decay_rate_avg": r["decay_rate_avg"],
            "verdict": r["verdict"],
            "signal_decay_t5": r["signal_decay_t5"],
            "signal_decay_t10": r["signal_decay_t10"],
            "signal_decay_t20": r["signal_decay_t20"],
            "stock_count": r["stock_count"],
            "approved": r.get("approved", False),
        })
    df = pd.DataFrame(rows)
    # 處理 NaN → None（Supabase 需要 NULL）
    df = df.where(df.notna(), None)
    return save_to_db(df, "strategy_tournament_results")


def _build_report(results: list[dict], approved: list[str], run_date: str) -> str:
    """產生 Markdown 報告"""
    lines: list[str] = []
    lines.append(f"# 策略淘汰賽報告 ({run_date})")
    lines.append("")
    lines.append(f"> 評估 {len(results)} 個策略，篩選門檻：OOS Sharpe > {OOS_SHARPE_MIN}、Decay Rate < {DECAY_RATE_MAX}")
    lines.append(f"> 通過策略：{len(approved)} 個")
    lines.append("")

    # 通過的策略
    lines.append("## 通過策略（進入 Paper Trading）")
    lines.append("")
    if approved:
        lines.append("| 策略 | IS Sharpe | OOS Sharpe | Decay Rate | Verdict | T+5 | T+10 | T+20 | 股票數 |")
        lines.append("|------|-----------|------------|------------|---------|-----|------|------|--------|")
        for r in results:
            if r["name"] in approved:
                lines.append(
                    f"| {r['name']} "
                    f"| {_fmt(r['is_sharpe_avg'])} "
                    f"| {_fmt(r['oos_sharpe_avg'])} "
                    f"| {_fmt(r['decay_rate_avg'])} "
                    f"| {r['verdict']} "
                    f"| {_pct(r['signal_decay_t5'])} "
                    f"| {_pct(r['signal_decay_t10'])} "
                    f"| {_pct(r['signal_decay_t20'])} "
                    f"| {r['stock_count']} |"
                )
        lines.append("")
    else:
        lines.append("*無策略通過篩選門檻*")
        lines.append("")

    # 完整排名
    lines.append("## 完整排名")
    lines.append("")
    lines.append("| # | 策略 | IS Sharpe | OOS Sharpe | Decay Rate | Verdict | T+5 | T+10 | T+20 | 通過 |")
    lines.append("|---|------|-----------|------------|------------|---------|-----|------|------|------|")

    # 依 OOS Sharpe 排序
    sorted_results = sorted(
        results,
        key=lambda r: r["oos_sharpe_avg"] if np.isfinite(r.get("oos_sharpe_avg", np.nan)) else -999,
        reverse=True,
    )
    for i, r in enumerate(sorted_results, 1):
        passed = "V" if r["name"] in approved else ""
        lines.append(
            f"| {i} "
            f"| {r['name']} "
            f"| {_fmt(r['is_sharpe_avg'])} "
            f"| {_fmt(r['oos_sharpe_avg'])} "
            f"| {_fmt(r['decay_rate_avg'])} "
            f"| {r['verdict']} "
            f"| {_pct(r['signal_decay_t5'])} "
            f"| {_pct(r['signal_decay_t10'])} "
            f"| {_pct(r['signal_decay_t20'])} "
            f"| {passed} |"
        )
    lines.append("")

    # 篩選門檻說明
    lines.append("## 篩選規則")
    lines.append("")
    lines.append(f"- OOS Sharpe Ratio > {OOS_SHARPE_MIN}")
    lines.append(f"- Decay Rate < {DECAY_RATE_MAX}（IS→OOS 績效衰退幅度）")
    lines.append("- Verdict: stable (<20%) / moderate (<50%) / severe (<80%) / overfitting (>=80%)")
    lines.append("- T+N: 買入訊號後 N 天平均報酬率")
    lines.append("")

    return "\n".join(lines)


def _fmt(val: float | None) -> str:
    """格式化數字"""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "-"
    return f"{val:.3f}"


def _pct(val: float | None) -> str:
    """格式化百分比"""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "-"
    return f"{val * 100:.2f}%"


# ===================================================================
# 主入口
# ===================================================================

def run_tournament(
    force: bool = False,
    oos_sharpe_min: float = OOS_SHARPE_MIN,
    decay_rate_max: float = DECAY_RATE_MAX,
) -> dict:
    """執行策略淘汰賽

    Args:
        force: 強制重新跑（忽略快取）
        oos_sharpe_min: OOS Sharpe 最低門檻
        decay_rate_max: Decay Rate 最高門檻

    Returns: {
        approved_strategies: list[str],
        full_ranking: list[dict],
        report_path: str | None,
        run_date: str,
    }
    """
    # 檢查是否需要重新跑
    if not _should_rerun(force):
        cached = _load_cached_results()
        if cached:
            logger.info(f"使用快取結果：{len(cached['approved_strategies'])} 個策略通過")
            return {**cached, "report_path": None}

    run_date = datetime.now().strftime("%Y-%m-%d")
    logger.info(f"開始策略淘汰賽 ({run_date})")
    logger.info(f"篩選門檻：OOS Sharpe > {oos_sharpe_min}, Decay Rate < {decay_rate_max}")

    # Step 1: 選出代表性股票
    stock_ids = _load_representative_stocks()

    # Step 2: 載入資料
    start_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    all_stock_data = _load_tournament_data(stock_ids, start_date)

    if not all_stock_data:
        logger.error("無法載入任何股票資料，淘汰賽中止")
        return {
            "approved_strategies": [],
            "full_ranking": [],
            "report_path": None,
            "run_date": run_date,
        }

    # 載入產業分類（次產業輪動策略需要）
    ind_map: dict[str, dict] = {}
    try:
        ind_df = safe_read_sql("SELECT stock_id, sector, sub_industry FROM industry_classification")
        for _, row in ind_df.iterrows():
            ind_map[row["stock_id"]] = {
                "sector": row.get("sector"),
                "sub_industry": row.get("sub_industry"),
            }
    except Exception:
        pass

    # Step 3: 評估所有策略
    results: list[dict] = []
    for i, (name, cls) in enumerate(STRATEGY_MAP.items(), 1):
        logger.info(f"[{i}/{len(STRATEGY_MAP)}] 評估策略: {name}")
        result = _evaluate_strategy(name, cls, all_stock_data, ind_map)
        results.append(result)
        logger.info(
            f"  IS Sharpe={_fmt(result['is_sharpe_avg'])}, "
            f"OOS Sharpe={_fmt(result['oos_sharpe_avg'])}, "
            f"Decay={_fmt(result['decay_rate_avg'])}, "
            f"Verdict={result['verdict']}"
        )

    # Step 4: 篩選
    approved: list[str] = []
    for r in results:
        oos_ok = (
            isinstance(r["oos_sharpe_avg"], (int, float))
            and np.isfinite(r["oos_sharpe_avg"])
            and r["oos_sharpe_avg"] > oos_sharpe_min
        )
        decay_ok = (
            isinstance(r["decay_rate_avg"], (int, float))
            and np.isfinite(r["decay_rate_avg"])
            and r["decay_rate_avg"] < decay_rate_max
        )
        is_approved = oos_ok and decay_ok
        r["approved"] = is_approved
        if is_approved:
            approved.append(r["name"])

    logger.info(f"篩選結果：{len(approved)}/{len(results)} 個策略通過")
    for name in approved:
        logger.info(f"  V {name}")

    # Step 5: 儲存結果
    _save_results(results, run_date)

    # Step 6: 產生報告
    report_content = _build_report(results, approved, run_date)
    reports_dir = PROJECT_ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)
    report_path = reports_dir / "strategy_tournament.md"
    report_path.write_text(report_content, encoding="utf-8")
    logger.info(f"報告已產生: {report_path}")

    return {
        "approved_strategies": approved,
        "full_ranking": results,
        "report_path": str(report_path),
        "run_date": run_date,
    }


def get_approved_strategies() -> list[tuple[str, type]]:
    """取得已核准的策略清單（供 paper_trader 使用）

    優先從 DB 快取讀取，若無則跑淘汰賽。

    Returns: [(strategy_name, strategy_class), ...]
    """
    cached = _load_cached_results()
    if cached and cached.get("approved_strategies"):
        names = cached["approved_strategies"]
    else:
        logger.info("無快取結果，執行淘汰賽")
        result = run_tournament()
        names = result["approved_strategies"]

    strategies = []
    for name in names:
        cls = STRATEGY_MAP.get(name)
        if cls:
            strategies.append((name, cls))
        else:
            logger.warning(f"策略 {name!r} 不在 STRATEGY_MAP 中，跳過")

    if not strategies:
        logger.warning("無核准策略，fallback 到預設策略")
        fallback_names = ["RSI 反轉", "MA 交叉", "量價動能", "趨勢過濾MA", "MACD 訊號"]
        for name in fallback_names:
            cls = STRATEGY_MAP.get(name)
            if cls:
                strategies.append((name, cls))

    return strategies


# ===================================================================
# CLI
# ===================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="策略淘汰賽 — OOS 驗證篩選")
    parser.add_argument("--force", action="store_true", help="強制重新跑（忽略快取）")
    parser.add_argument(
        "--oos-sharpe-min", type=float, default=OOS_SHARPE_MIN,
        help=f"OOS Sharpe 最低門檻（預設 {OOS_SHARPE_MIN}）",
    )
    parser.add_argument(
        "--decay-rate-max", type=float, default=DECAY_RATE_MAX,
        help=f"Decay Rate 最高門檻（預設 {DECAY_RATE_MAX}）",
    )
    args = parser.parse_args()
    run_tournament(
        force=args.force,
        oos_sharpe_min=args.oos_sharpe_min,
        decay_rate_max=args.decay_rate_max,
    )
