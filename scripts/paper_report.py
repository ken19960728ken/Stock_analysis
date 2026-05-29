"""
Paper Trading 報告模組 — 日報 + 週報 + 告警

負責：
1. 每日交易摘要（持倉、交易、損益、風控狀態）
2. 每週績效報告（策略貢獻、基準比較、風險指標）
3. 異常告警（回撤超閾值、策略失效）
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.db import safe_read_sql
from core.logger import setup_logger
from core.notifier import send_alert_email, send_report_email

logger = setup_logger("paper_report")


# ===================================================================
# 日報
# ===================================================================

def generate_daily_report(trade_date: str) -> str | None:
    """產生每日 Paper Trading 報告

    Args:
        trade_date: 交易日期 YYYY-MM-DD

    Returns: 報告檔案路徑，或 None（無資料）
    """
    # 載入當日資料
    try:
        pnl_df = safe_read_sql(
            "SELECT * FROM paper_daily_pnl WHERE trade_date = %(d)s",
            params={"d": trade_date},
        )
        trades_df = safe_read_sql(
            "SELECT * FROM paper_trades WHERE trade_date = %(d)s ORDER BY side",
            params={"d": trade_date},
        )
        holdings_df = safe_read_sql(
            "SELECT * FROM paper_portfolio WHERE trade_date = %(d)s "
            "ORDER BY market_value DESC",
            params={"d": trade_date},
        )
    except Exception as e:
        logger.warning(f"載入報告資料失敗: {e}")
        return None

    if pnl_df.empty:
        logger.info(f"無 {trade_date} 的損益資料，跳過報告")
        return None

    pnl = pnl_df.iloc[0]

    lines: list[str] = []
    lines.append(f"# Paper Trading 日報 ({trade_date})")
    lines.append("")

    # 組合總覽
    lines.append("## 組合總覽")
    lines.append("")
    lines.append(f"| 項目 | 數值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 總資產 | {_money(pnl.get('total_equity'))} |")
    lines.append(f"| 現金 | {_money(pnl.get('cash'))} |")
    lines.append(f"| 持倉市值 | {_money(pnl.get('positions_value'))} |")
    lines.append(f"| 持股數 | {pnl.get('position_count', 0)} |")
    lines.append(f"| 今日損益 | {_money(pnl.get('daily_pnl'))} ({_pct(pnl.get('daily_pnl_pct'))}) |")
    lines.append(f"| 累積報酬 | {_pct(pnl.get('cumulative_return'))} |")
    lines.append(f"| 回撤 | {_pct(pnl.get('drawdown_pct'))} |")
    lines.append(f"| 風控狀態 | {pnl.get('risk_status', 'normal')} |")

    var_95 = pnl.get("var_95")
    if var_95 is not None:
        lines.append(f"| VaR(95%) | {_pct(var_95)} |")
    sharpe = pnl.get("sharpe_ratio")
    if sharpe is not None:
        lines.append(f"| Sharpe Ratio | {_fmt(sharpe)} |")
    lines.append("")

    # 今日交易
    lines.append("## 今日交易")
    lines.append("")
    if trades_df.empty:
        lines.append("*無交易*")
    else:
        lines.append("| 方向 | 股票 | 股數 | 價格 | 金額 | 策略 | 原因 | 已實現損益 |")
        lines.append("|------|------|------|------|------|------|------|-----------|")
        for _, t in trades_df.iterrows():
            side_label = "買入" if t["side"] == "buy" else "賣出"
            rpnl = _money(t.get("realized_pnl")) if t["side"] == "sell" else "-"
            lines.append(
                f"| {side_label} "
                f"| {t['stock_id']} "
                f"| {t.get('shares', 0):,} "
                f"| {t.get('price', 0):.2f} "
                f"| {_money(t.get('amount'))} "
                f"| {t.get('strategy_name', '-')} "
                f"| {t.get('reason', '-')} "
                f"| {rpnl} |"
            )
    lines.append("")

    # 當前持倉
    lines.append("## 當前持倉")
    lines.append("")
    if holdings_df.empty:
        lines.append("*空倉*")
    else:
        lines.append("| 股票 | 股數 | 成本 | 現價 | 市值 | 未實現損益 | 比重 | 策略 |")
        lines.append("|------|------|------|------|------|-----------|------|------|")
        for _, h in holdings_df.iterrows():
            lines.append(
                f"| {h['stock_id']} "
                f"| {h.get('shares', 0):,} "
                f"| {h.get('entry_price', 0):.2f} "
                f"| {h.get('current_price', 0):.2f} "
                f"| {_money(h.get('market_value'))} "
                f"| {_money(h.get('unrealized_pnl'))} ({_pct(h.get('unrealized_pnl_pct'))}) "
                f"| {_pct(h.get('weight_pct'))} "
                f"| {h.get('strategy_name', '-')} |"
            )
    lines.append("")

    # 寫入檔案
    report_content = "\n".join(lines)
    reports_dir = PROJECT_ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)
    report_path = reports_dir / f"paper_trading_{trade_date}.md"
    report_path.write_text(report_content, encoding="utf-8")
    logger.info(f"日報已產生: {report_path}")

    return str(report_path)


# ===================================================================
# 週報
# ===================================================================

def generate_weekly_report(end_date: str) -> str | None:
    """產生每週 Paper Trading 報告

    Args:
        end_date: 週末交易日期

    Returns: 報告檔案路徑
    """
    start_date = (
        datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=7)
    ).strftime("%Y-%m-%d")

    try:
        pnl_df = safe_read_sql(
            "SELECT * FROM paper_daily_pnl "
            "WHERE trade_date >= %(sd)s AND trade_date <= %(ed)s "
            "ORDER BY trade_date",
            params={"sd": start_date, "ed": end_date},
        )
        trades_df = safe_read_sql(
            "SELECT * FROM paper_trades "
            "WHERE trade_date >= %(sd)s AND trade_date <= %(ed)s",
            params={"sd": start_date, "ed": end_date},
        )
    except Exception as e:
        logger.warning(f"載入週報資料失敗: {e}")
        return None

    if pnl_df.empty:
        return None

    first = pnl_df.iloc[0]
    last = pnl_df.iloc[-1]

    lines: list[str] = []
    lines.append(f"# Paper Trading 週報 ({start_date} ~ {end_date})")
    lines.append("")

    # 週績效
    week_return = 0.0
    start_equity = first.get("total_equity", 0)
    end_equity = last.get("total_equity", 0)
    if start_equity > 0:
        week_return = (end_equity - start_equity) / start_equity

    lines.append("## 週績效摘要")
    lines.append("")
    lines.append(f"| 項目 | 數值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 週報酬 | {_pct(week_return)} |")
    lines.append(f"| 期末資產 | {_money(end_equity)} |")
    lines.append(f"| 累積報酬 | {_pct(last.get('cumulative_return'))} |")
    lines.append(f"| 最大回撤 | {_pct(pnl_df['drawdown_pct'].min())} |")
    lines.append(f"| 交易筆數 | {len(trades_df)} |")
    lines.append("")

    # 策略貢獻
    if not trades_df.empty:
        sell_trades = trades_df[trades_df["side"] == "sell"]
        if not sell_trades.empty:
            lines.append("## 策略貢獻（已實現）")
            lines.append("")
            lines.append("| 策略 | 交易數 | 總損益 | 勝率 |")
            lines.append("|------|--------|--------|------|")
            for strategy, grp in sell_trades.groupby("strategy_name"):
                total_pnl = grp["realized_pnl"].sum()
                win_count = (grp["realized_pnl"] > 0).sum()
                win_rate = win_count / len(grp) if len(grp) > 0 else 0
                lines.append(
                    f"| {strategy} | {len(grp)} | {_money(total_pnl)} | {_pct(win_rate)} |"
                )
            lines.append("")

    # 每日損益
    lines.append("## 每日損益")
    lines.append("")
    lines.append("| 日期 | 總資產 | 日損益 | 回撤 | 風控 |")
    lines.append("|------|--------|--------|------|------|")
    for _, row in pnl_df.iterrows():
        lines.append(
            f"| {str(row['trade_date'])[:10]} "
            f"| {_money(row.get('total_equity'))} "
            f"| {_money(row.get('daily_pnl'))} ({_pct(row.get('daily_pnl_pct'))}) "
            f"| {_pct(row.get('drawdown_pct'))} "
            f"| {row.get('risk_status', 'normal')} |"
        )
    lines.append("")

    # 寫入檔案
    report_content = "\n".join(lines)
    reports_dir = PROJECT_ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)
    report_path = reports_dir / f"paper_trading_weekly_{end_date}.md"
    report_path.write_text(report_content, encoding="utf-8")
    logger.info(f"週報已產生: {report_path}")

    return str(report_path)


# ===================================================================
# Email 發送
# ===================================================================

def send_daily_email(report_path: str) -> bool:
    """發送日報 Email"""
    return send_report_email(report_path, subject="Paper Trading 日報")


def send_weekly_email(report_path: str) -> bool:
    """發送週報 Email"""
    return send_report_email(report_path, subject="Paper Trading 週報")


def check_and_send_alerts(alerts: list[dict]) -> None:
    """檢查並發送告警 Email"""
    if not alerts:
        return

    critical_alerts = [a for a in alerts if a.get("severity") == "critical"]
    warning_alerts = [a for a in alerts if a.get("severity") == "warning"]

    if critical_alerts:
        body_lines = ["Paper Trading 觸發以下嚴重告警：", ""]
        for a in critical_alerts:
            body_lines.append(f"  - [{a['type']}] {a['message']}")
        body_lines.append("")
        body_lines.append("請立即檢查 Paper Trading 狀態。")
        send_alert_email(
            subject="Paper Trading 嚴重告警",
            body="\n".join(body_lines),
            severity="critical",
        )

    if warning_alerts:
        body_lines = ["Paper Trading 觸發以下警告：", ""]
        for a in warning_alerts:
            body_lines.append(f"  - [{a['type']}] {a['message']}")
        send_alert_email(
            subject="Paper Trading 警告",
            body="\n".join(body_lines),
            severity="warning",
        )


def is_week_end(trade_date: str) -> bool:
    """判斷是否為本週最後一個交易日（週五或接近週末）"""
    dt = datetime.strptime(trade_date, "%Y-%m-%d")
    return dt.weekday() == 4  # 週五


# ===================================================================
# 格式化工具
# ===================================================================

def _money(val) -> str:
    """格式化金額"""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "-"
    return f"{float(val):+,.0f}" if val != 0 else "0"


def _pct(val) -> str:
    """格式化百分比"""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "-"
    return f"{float(val):+.2%}"


def _fmt(val) -> str:
    """格式化數字"""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "-"
    return f"{float(val):.3f}"
