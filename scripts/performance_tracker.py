"""
績效追蹤 — 回填推薦績效 + 產出追蹤報告

用法:
    uv run python scripts/performance_tracker.py                  # 回填 + 產出報告
    uv run python scripts/performance_tracker.py --backfill-only  # 僅回填
    uv run python scripts/performance_tracker.py --report-only    # 僅產報告
"""

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.db import get_engine, safe_read_sql
from core.logger import setup_logger

logger = setup_logger("performance_tracker")


# ===================================================================
# 交易日價格計算
# ===================================================================

def _calc_trading_day_prices(prices_after: pd.DataFrame) -> dict:
    """
    從推薦日之後的交易日價格序列，取 T+5/T+10/T+20 的收盤價。

    Parameters
    ----------
    prices_after : DataFrame
        推薦日之後的交易日價格（已按 date 排序），
        必須包含 date, close 欄位。

    Returns
    -------
    dict : {"price_t5": float|None, "price_t10": ..., "price_t20": ...}
    """
    result = {"price_t5": None, "price_t10": None, "price_t20": None}
    if prices_after is None or prices_after.empty:
        return result

    n = len(prices_after)
    if n >= 5:
        result["price_t5"] = float(prices_after.iloc[4]["close"])
    if n >= 10:
        result["price_t10"] = float(prices_after.iloc[9]["close"])
    if n >= 20:
        result["price_t20"] = float(prices_after.iloc[19]["close"])

    return result


# ===================================================================
# 績效回填
# ===================================================================

def backfill_performance() -> int:
    """
    回填歷史推薦的 T+5/T+10/T+20 績效。

    查詢 recommendation_history 中 return_t5/t10/t20 為 NULL 的記錄，
    從 daily_price 取推薦日之後的交易日收盤價計算報酬率。

    Returns
    -------
    int : 本次更新的記錄數
    """
    # 查詢待回填的記錄
    pending = safe_read_sql(
        "SELECT id, report_date, stock_id, entry_price, "
        "return_t5, return_t10, return_t20 "
        "FROM recommendation_history "
        "WHERE return_t5 IS NULL OR return_t10 IS NULL OR return_t20 IS NULL "
        "ORDER BY report_date"
    )

    if pending.empty:
        logger.info("無待回填記錄")
        return 0

    logger.info(f"待回填記錄: {len(pending)} 筆")

    engine = get_engine()
    updated = 0

    # 按 (stock_id, report_date) 逐筆處理
    for _, row in pending.iterrows():
        sid = row["stock_id"]
        report_date = row["report_date"]
        entry_price = row["entry_price"]
        rec_id = row["id"]

        if entry_price is None or entry_price <= 0:
            continue

        # 取推薦日之後的交易日價格
        prices_after = safe_read_sql(
            "SELECT date, close FROM daily_price "
            "WHERE stock_id = %(sid)s AND date > %(rd)s "
            "ORDER BY date LIMIT 25",
            params={"sid": sid, "rd": report_date},
        )

        if prices_after.empty:
            continue

        td_prices = _calc_trading_day_prices(prices_after)

        # 計算報酬率（只更新目前為 NULL 的欄位）
        updates = {}
        if row["return_t5"] is None and td_prices["price_t5"] is not None:
            updates["price_t5"] = td_prices["price_t5"]
            updates["return_t5"] = round(
                (td_prices["price_t5"] / entry_price - 1) * 100, 2
            )
        if row["return_t10"] is None and td_prices["price_t10"] is not None:
            updates["price_t10"] = td_prices["price_t10"]
            updates["return_t10"] = round(
                (td_prices["price_t10"] / entry_price - 1) * 100, 2
            )
        if row["return_t20"] is None and td_prices["price_t20"] is not None:
            updates["price_t20"] = td_prices["price_t20"]
            updates["return_t20"] = round(
                (td_prices["price_t20"] / entry_price - 1) * 100, 2
            )

        if not updates:
            continue

        # UPDATE
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        sql = text(f"UPDATE recommendation_history SET {set_clause} WHERE id = :rec_id")
        params = {**updates, "rec_id": rec_id}
        try:
            with engine.connect() as conn:
                conn.execute(sql, params)
                conn.commit()
            updated += 1
        except Exception as e:
            logger.error(f"回填失敗 id={rec_id}: {e}")

    logger.info(f"回填完成: {updated} 筆更新")
    return updated


# ===================================================================
# 績效追蹤報告
# ===================================================================

def generate_performance_report(output_dir: str | None = None) -> str:
    """
    產出績效追蹤 Markdown 報告。

    Returns
    -------
    str : 報告內容（Markdown 字串）
    """
    df = safe_read_sql(
        "SELECT * FROM recommendation_history ORDER BY report_date DESC, rank"
    )

    lines = ["# 選股績效追蹤報告\n"]

    if df.empty:
        lines.append("尚無推薦記錄。系統將從下次產出選股報告時開始追蹤。\n")
        report_text = "\n".join(lines)
        _save_report(report_text, output_dir)
        return report_text

    latest_date = df["report_date"].max()
    earliest_date = df["report_date"].min()
    lines.append(f"> 更新日期：{latest_date}")
    lines.append(f"> 追蹤期間：{earliest_date} ~ {latest_date}")
    lines.append(f"> 累計推薦：{len(df)} 筆\n")

    # 整體績效
    lines.append("## 整體績效\n")
    lines.append("| 指標 | T+5 | T+10 | T+20 |")
    lines.append("|------|-----|------|------|")

    for label, col in [("平均報酬", "return"), ("勝率", "win")]:
        vals = []
        for t in ["t5", "t10", "t20"]:
            col_name = f"return_{t}"
            valid = df[col_name].dropna()
            if valid.empty:
                vals.append("—")
            elif label == "平均報酬":
                vals.append(f"{valid.mean():+.2f}%")
            else:
                vals.append(f"{(valid > 0).mean() * 100:.0f}%")
        lines.append(f"| {label} | {vals[0]} | {vals[1]} | {vals[2]} |")

    # 樣本數
    sample_vals = []
    for t in ["t5", "t10", "t20"]:
        sample_vals.append(str(df[f"return_{t}"].notna().sum()))
    lines.append(f"| 樣本數 | {sample_vals[0]} | {sample_vals[1]} | {sample_vals[2]} |")
    lines.append("")

    # 按策略拆分（從 JSONB 解析）
    _add_strategy_breakdown(df, lines)

    # 最近推薦追蹤
    _add_recent_tracking(df, lines)

    # 版本變更記錄
    _add_version_changes(df, lines)

    lines.append("---\n")
    lines.append("*本報告由績效追蹤系統自動產出*\n")

    report_text = "\n".join(lines)
    _save_report(report_text, output_dir)
    return report_text


def _add_strategy_breakdown(df: pd.DataFrame, lines: list):
    """按策略拆分勝率"""
    # 只分析有 T+5 績效的記錄
    has_t5 = df[df["return_t5"].notna()].copy()
    if has_t5.empty or "strategy_votes" not in has_t5.columns:
        return

    lines.append("## 按策略拆分（投正分的策略）\n")
    lines.append("| 策略 | 推薦次數 | T+5 勝率 | T+5 均報酬 |")
    lines.append("|------|---------|---------|----------|")

    # 統計每個策略「投正分」時的後續表現
    strategy_stats: dict[str, list] = {}
    for _, row in has_t5.iterrows():
        votes = row["strategy_votes"]
        if not isinstance(votes, dict):
            continue
        for name, v in votes.items():
            if isinstance(v, dict) and v.get("recent_score", 0) > 0:
                strategy_stats.setdefault(name, []).append(row["return_t5"])

    for name in sorted(strategy_stats, key=lambda x: -len(strategy_stats[x])):
        returns = strategy_stats[name]
        count = len(returns)
        if count < 3:
            continue
        win_rate = sum(1 for r in returns if r > 0) / count * 100
        avg_ret = sum(returns) / count
        lines.append(f"| {name} | {count} | {win_rate:.0f}% | {avg_ret:+.2f}% |")

    lines.append("")


def _add_recent_tracking(df: pd.DataFrame, lines: list):
    """最近 5 日推薦追蹤"""
    recent_dates = sorted(df["report_date"].unique(), reverse=True)[:5]
    recent = df[df["report_date"].isin(recent_dates)].copy()

    if recent.empty:
        return

    lines.append("## 最近推薦追蹤\n")
    lines.append("| 日期 | 排名 | 股票 | 推薦價 | T+5 | T+10 | T+20 | 版本 |")
    lines.append("|------|------|------|-------|-----|------|------|------|")

    for _, row in recent.iterrows():
        date_str = pd.Timestamp(row["report_date"]).strftime("%m/%d")
        name_str = f"{row['stock_id']} {row.get('stock_name', '')}"
        commit_short = str(row.get("git_commit", ""))[:7]

        t5 = f"{row['return_t5']:+.1f}%" if pd.notna(row.get("return_t5")) else "—"
        t10 = f"{row['return_t10']:+.1f}%" if pd.notna(row.get("return_t10")) else "—"
        t20 = f"{row['return_t20']:+.1f}%" if pd.notna(row.get("return_t20")) else "—"

        lines.append(
            f"| {date_str} | #{row.get('rank', '—')} | {name_str} | "
            f"{row['entry_price']:.1f} | {t5} | {t10} | {t20} | {commit_short} |"
        )
    lines.append("")


def _add_version_changes(df: pd.DataFrame, lines: list):
    """版本變更記錄 — 標記策略 hash 變更的日期"""
    if "strategy_hashes" not in df.columns or "git_commit" not in df.columns:
        return

    # 取每日唯一的 git_commit（從推薦記錄中）
    daily_versions = (
        df.groupby("report_date")
        .agg({"git_commit": "first", "app_version": "first"})
        .sort_index()
    )

    if len(daily_versions) < 2:
        return

    lines.append("## 版本變更記錄\n")
    lines.append("| 日期 | Git Commit | App Version |")
    lines.append("|------|-----------|-------------|")

    prev_commit = None
    for date, row in daily_versions.iterrows():
        commit = str(row["git_commit"])[:7]
        ver = row.get("app_version", "—")
        if prev_commit is None or commit != prev_commit:
            date_str = pd.Timestamp(date).strftime("%Y-%m-%d")
            lines.append(f"| {date_str} | {commit} | {ver} |")
        prev_commit = commit
    lines.append("")


def _save_report(report_text: str, output_dir: str | None = None):
    """寫入 performance_tracking.md"""
    if output_dir is None:
        output_dir = str(PROJECT_ROOT / "reports")
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, "performance_tracking.md")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_text)
    logger.info(f"績效追蹤報告已儲存: {filepath}")


# ===================================================================
# CLI
# ===================================================================

def main():
    parser = argparse.ArgumentParser(description="選股績效追蹤")
    parser.add_argument("--backfill-only", action="store_true", help="僅回填績效")
    parser.add_argument("--report-only", action="store_true", help="僅產出報告")
    parser.add_argument("--output", type=str, default=None, help="報告輸出目錄")
    args = parser.parse_args()

    if args.backfill_only:
        backfill_performance()
    elif args.report_only:
        generate_performance_report(output_dir=args.output)
    else:
        backfill_performance()
        generate_performance_report(output_dir=args.output)


if __name__ == "__main__":
    main()
