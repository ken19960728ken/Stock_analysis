"""
價值投資全市場回測報告

對指定台股執行價值投資策略回測 3 年，產出含 P/E、殖利率、營收 YoY 的詳細交易報告。

用法:
    uv run python scripts/value_investing_report.py                      # 預設 3 支測試股
    uv run python scripts/value_investing_report.py --stocks 2330 2317   # 指定股票
    uv run python scripts/value_investing_report.py --all                # 全市場
"""

import argparse
import sys
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

# 確保專案根目錄在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analysis.strategies.value_investing import ValueInvestingStrategy
from analysis.utils.backtester import Backtester
from analysis.utils.charts import create_equity_curve
from core.db import get_engine, safe_read_sql
from core.logger import setup_logger

logger = setup_logger("value_report")

DEFAULT_STOCKS = ["2330", "2317", "2382"]
LOOKBACK_YEARS = 3


# ---------------------------------------------------------------------------
# 資料載入（直接 pd.read_sql，不依賴 Streamlit）
# ---------------------------------------------------------------------------

def load_daily_price(engine, stock_id: str, start_date: str) -> pd.DataFrame:
    sql = text(
        "SELECT * FROM daily_price "
        "WHERE stock_id = :sid AND date >= :start "
        "ORDER BY date"
    )
    df = safe_read_sql(sql, params={"sid": stock_id, "start": start_date})
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    return df


def load_stock_per(engine, stock_id: str, start_date: str) -> pd.DataFrame:
    sql = text(
        'SELECT date, "PER", dividend_yield FROM stock_per '
        "WHERE stock_id = :sid AND date >= :start "
        "ORDER BY date"
    )
    df = safe_read_sql(sql, params={"sid": stock_id, "start": start_date})
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    return df


def load_month_revenue(engine, stock_id: str, start_date: str) -> pd.DataFrame:
    """載入月營收並計算 YoY（同期月份營收年增率）"""
    # 多抓 1 年資料以計算 YoY
    extended_start = (pd.Timestamp(start_date) - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
    sql = text(
        "SELECT date, revenue, revenue_month, revenue_year FROM month_revenue "
        "WHERE stock_id = :sid AND date >= :start "
        "ORDER BY date"
    )
    df = safe_read_sql(sql, params={"sid": stock_id, "start": extended_start})
    if df.empty:
        return pd.DataFrame(columns=["date", "revenue_yoy"])
    df["date"] = pd.to_datetime(df["date"])
    df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce")

    # 計算 YoY：同月份去年營收
    df = df.sort_values(["revenue_month", "revenue_year"])
    df["prev_year_revenue"] = df.groupby("revenue_month")["revenue"].shift(1)
    df["revenue_yoy"] = (
        (df["revenue"] - df["prev_year_revenue"]) / df["prev_year_revenue"].replace(0, float("nan")) * 100
    )
    df = df.sort_values("date")

    # 只回傳 start_date 之後的資料
    df = df[df["date"] >= pd.Timestamp(start_date)]
    return df[["date", "revenue_yoy"]]


def load_stock_name(engine, stock_id: str) -> str:
    sql = text(
        'SELECT "商品名稱" FROM twstock_code WHERE "商品代號" = :sid LIMIT 1'
    )
    with engine.connect() as conn:
        row = conn.execute(sql, {"sid": stock_id}).fetchone()
    return row[0] if row else ""


def load_all_stock_ids(engine) -> list[str]:
    sql = text(
        'SELECT "商品代號" FROM twstock_code '
        "WHERE \"CFICode\" = 'ESVUFR' OR \"商品類型\" = 'ETF' "
        'ORDER BY "商品代號"'
    )
    with engine.connect() as conn:
        rows = conn.execute(sql).fetchall()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# 工具函數
# ---------------------------------------------------------------------------

def get_reference_quarter(entry_date: pd.Timestamp) -> str:
    """反推 entry_date 之前最近已公告的財報季度"""
    q_ends = [
        (3, 31),   # Q1
        (6, 30),   # Q2
        (9, 30),   # Q3
        (12, 31),  # Q4
    ]
    d = entry_date
    candidates = []
    for m, day in q_ends:
        qe = pd.Timestamp(year=d.year, month=m, day=day)
        if qe < d:
            candidates.append(qe)
        qe_prev = pd.Timestamp(year=d.year - 1, month=m, day=day)
        candidates.append(qe_prev)

    candidates = [c for c in candidates if c < d]
    if not candidates:
        return "N/A"
    nearest = max(candidates)
    q_map = {3: "Q1", 6: "Q2", 9: "Q3", 12: "Q4"}
    return f"{nearest.year}{q_map[nearest.month]}"


def get_exit_reason(row, pe_th=15, dy_th=3.0, rev_th=0) -> str:
    """根據出場日的基本面數值，判斷哪些條件不再滿足"""
    reasons = []
    pe = row.get("PER")
    dy = row.get("DividendYield")
    yoy = row.get("revenue_yoy")

    if pd.notna(pe) and pe > 0:
        if pe >= pe_th:
            reasons.append(f"P/E={pe:.1f}≥{pe_th}")
    if pd.notna(dy):
        if dy <= dy_th:
            reasons.append(f"殖利率={dy:.1f}%≤{dy_th}%")
    if pd.notna(yoy):
        if yoy <= rev_th:
            reasons.append(f"營收YoY={yoy:.1f}%≤{rev_th}%")

    return "; ".join(reasons) if reasons else "條件綜合不達標"


def merge_fundamental_data(daily: pd.DataFrame, per: pd.DataFrame, rev: pd.DataFrame) -> pd.DataFrame:
    """將 stock_per（日頻）和 month_revenue（月頻 YoY）合併到 daily_price"""
    # stock_per 日頻 → left merge（DB 欄位: PER, dividend_yield）
    if not per.empty:
        daily = daily.merge(per[["date", "PER", "dividend_yield"]], on="date", how="left")
    else:
        daily["PER"] = float("nan")
        daily["dividend_yield"] = float("nan")

    # month_revenue 月頻 → merge_asof backward
    if not rev.empty:
        daily = daily.sort_values("date")
        rev = rev.sort_values("date")
        daily = pd.merge_asof(
            daily,
            rev[["date", "revenue_yoy"]],
            on="date",
            direction="backward",
        )
    else:
        daily["revenue_yoy"] = float("nan")

    # 欄位重命名，讓策略能自動偵測
    daily = daily.rename(columns={
        "dividend_yield": "DividendYield",
    })
    return daily


# ---------------------------------------------------------------------------
# 0050 買入持有基準
# ---------------------------------------------------------------------------

def calc_benchmark_buyhold(engine, start_date: str, initial_capital: float = 1_000_000) -> dict | None:
    """計算 0050 買入持有績效作為基準比較

    Returns:
        dict with equity_curve (pd.Series), total_return, annual_return,
        sharpe_ratio, max_drawdown; or None if data insufficient.
    """
    df = load_daily_price(engine, "0050", start_date)
    if df.empty or len(df) < 2:
        logger.warning("0050 資料不足，無法計算基準")
        return None

    commission_rate = 0.001425
    first_close = df.iloc[0]["close"]
    shares = int(initial_capital / (first_close * (1 + commission_rate)) / 1000) * 1000
    if shares <= 0:
        return None
    buy_cost = shares * first_close * (1 + commission_rate)
    cash = initial_capital - buy_cost

    equity_vals = cash + shares * df["close"].values
    equity_curve = pd.Series(equity_vals, index=df["date"])

    # 績效指標
    total_return = (equity_curve.iloc[-1] / initial_capital) - 1
    days = (equity_curve.index[-1] - equity_curve.index[0]).days
    annual_return = (1 + total_return) ** (365 / days) - 1 if days > 0 else 0.0

    returns = equity_curve.pct_change().dropna()
    rf = 0.015
    if len(returns) > 1 and returns.std() > 0:
        sharpe_ratio = (returns.mean() - rf / 252) / returns.std() * np.sqrt(252)
    else:
        sharpe_ratio = 0.0

    peak = equity_curve.cummax()
    drawdown_curve = (equity_curve - peak) / peak
    max_drawdown = drawdown_curve.min()

    return {
        "equity_curve": equity_curve,
        "drawdown_curve": drawdown_curve,
        "total_return": total_return,
        "annual_return": annual_return,
        "sharpe_ratio": round(sharpe_ratio, 2),
        "max_drawdown": max_drawdown,
    }


# ---------------------------------------------------------------------------
# 單支股票回測
# ---------------------------------------------------------------------------

def backtest_one(engine, stock_id: str, start_date: str) -> tuple:
    """
    回傳 (result: BacktestResult, trades_detail: DataFrame, name: str)
    trades_detail 含額外的基本面欄位
    """
    name = load_stock_name(engine, stock_id)
    logger.info(f"回測 {stock_id} {name} ...")

    daily = load_daily_price(engine, stock_id, start_date)
    if daily.empty or len(daily) < 30:
        logger.warning(f"  {stock_id} 日K資料不足，跳過")
        return None, pd.DataFrame(), name

    per = load_stock_per(engine, stock_id, start_date)
    rev = load_month_revenue(engine, stock_id, start_date)

    df = merge_fundamental_data(daily, per, rev)

    strategy = ValueInvestingStrategy()
    bt = Backtester(strategy)
    result = bt.run(df)

    if result.trades.empty:
        logger.info(f"  {stock_id} 無交易")
        return result, pd.DataFrame(), name

    # 為每筆交易附加基本面資訊
    trades = result.trades.copy()
    trades["stock_id"] = stock_id
    trades["name"] = name

    # 建立日期→基本面 lookup
    lookup = df.set_index("date")[["PER", "DividendYield", "revenue_yoy"]]

    def _lookup_row(dt):
        """查找日期對應的基本面資料（精確匹配或往前找最近）"""
        if dt in lookup.index:
            row = lookup.loc[dt]
            return row.iloc[0] if isinstance(row, pd.DataFrame) else row
        prior = lookup.index[lookup.index <= dt]
        if len(prior) > 0:
            row = lookup.loc[prior[-1]]
            return row.iloc[0] if isinstance(row, pd.DataFrame) else row
        return None

    per_list = []
    dy_list = []
    yoy_list = []
    quarter_list = []
    exit_reason_list = []

    for _, t in trades.iterrows():
        # 進場日基本面
        ed = pd.Timestamp(t["entry_date"])
        entry_row = _lookup_row(ed)
        if entry_row is not None:
            per_list.append(entry_row.get("PER"))
            dy_list.append(entry_row.get("DividendYield"))
            yoy_list.append(entry_row.get("revenue_yoy"))
        else:
            per_list.append(None)
            dy_list.append(None)
            yoy_list.append(None)
        quarter_list.append(get_reference_quarter(ed))

        # 出場原因
        xd = pd.Timestamp(t["exit_date"])
        exit_row = _lookup_row(xd)
        if exit_row is not None:
            exit_reason_list.append(get_exit_reason(exit_row))
        else:
            exit_reason_list.append("N/A")

    trades["參考財報季"] = quarter_list
    trades["P/E"] = per_list
    trades["殖利率(%)"] = dy_list
    trades["營收YoY(%)"] = yoy_list
    trades["出場原因"] = exit_reason_list

    return result, trades, name


# ---------------------------------------------------------------------------
# 報告輸出
# ---------------------------------------------------------------------------

def print_performance_summary(stock_id: str, name: str, result):
    """印出單支股票績效摘要"""
    print(f"\n{'='*60}")
    print(f"  {stock_id} {name}  績效摘要")
    print(f"{'='*60}")
    print(f"  總報酬率:     {result.total_return:>8.2%}")
    print(f"  年化報酬:     {result.annual_return:>8.2%}")
    print(f"  Sharpe Ratio: {result.sharpe_ratio:>8.2f}")
    print(f"  最大回撤:     {result.max_drawdown:>8.2%}")
    print(f"  勝率:         {result.win_rate:>8.2%}")
    print(f"  交易次數:     {result.trade_count:>8d}")
    print(f"  平均持有天數: {result.avg_holding_days:>8.1f}")


def format_trades_for_display(trades: pd.DataFrame) -> pd.DataFrame:
    """整理交易報告欄位順序，N/A 處理"""
    if trades.empty:
        return trades

    cols = [
        "stock_id", "name", "entry_date", "exit_date",
        "參考財報季", "P/E", "殖利率(%)", "營收YoY(%)",
        "entry_price", "exit_price", "pnl_pct", "holding_days",
        "出場原因",
    ]
    out = trades[[c for c in cols if c in trades.columns]].copy()

    # 格式化
    for col in ["P/E", "殖利率(%)", "營收YoY(%)"]:
        if col in out.columns:
            out[col] = out[col].apply(
                lambda x: f"{x:.2f}" if pd.notna(x) else "N/A"
            )
    if "pnl_pct" in out.columns:
        out = out.rename(columns={"pnl_pct": "損益(%)"})

    return out


def main():
    parser = argparse.ArgumentParser(description="價值投資回測報告")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--stocks", nargs="+", help="指定股票代號")
    group.add_argument("--all", action="store_true", help="全市場回測")
    args = parser.parse_args()

    engine = get_engine()
    end_date = datetime.now()
    start_date = (end_date - timedelta(days=365 * LOOKBACK_YEARS)).strftime("%Y-%m-%d")

    # 決定股票清單
    if args.all:
        stock_ids = load_all_stock_ids(engine)
        logger.info(f"全市場模式：共 {len(stock_ids)} 支股票")
    elif args.stocks:
        stock_ids = args.stocks
    else:
        stock_ids = DEFAULT_STOCKS

    print(f"\n價值投資回測報告 — 回測期間: {start_date} ~ {end_date.strftime('%Y-%m-%d')}")
    print(f"股票清單: {', '.join(stock_ids)}")

    # 計算 0050 買入持有基準
    bench = calc_benchmark_buyhold(engine, start_date)
    if bench:
        print(f"\n{'='*60}")
        print("  0050 買入持有基準  績效摘要")
        print(f"{'='*60}")
        print(f"  總報酬率:     {bench['total_return']:>8.2%}")
        print(f"  年化報酬:     {bench['annual_return']:>8.2%}")
        print(f"  Sharpe Ratio: {bench['sharpe_ratio']:>8.2f}")
        print(f"  最大回撤:     {bench['max_drawdown']:>8.2%}")
    else:
        logger.warning("無法計算 0050 基準，圖表將不含基準線")

    all_trades = []
    results_summary = []
    # 收集 (stock_id, name, result) 用於圖表
    chart_data = []

    for sid in stock_ids:
        result, trades, name = backtest_one(engine, sid, start_date)

        if result is not None:
            print_performance_summary(sid, name, result)
            results_summary.append({
                "stock_id": sid,
                "name": name,
                "總報酬率(%)": round(result.total_return * 100, 2),
                "年化報酬(%)": round(result.annual_return * 100, 2),
                "Sharpe": result.sharpe_ratio,
                "最大回撤(%)": round(result.max_drawdown * 100, 2),
                "勝率(%)": round(result.win_rate * 100, 2),
                "交易次數": result.trade_count,
            })
            if not result.equity_curve.empty and result.trade_count > 0:
                chart_data.append((sid, name, result))

        if not trades.empty:
            all_trades.append(trades)

    # 彙整所有交易
    reports_dir = PROJECT_ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if all_trades:
        all_trades_df = pd.concat(all_trades, ignore_index=True)
        display_df = format_trades_for_display(all_trades_df)

        print(f"\n\n{'='*80}")
        print("  全部交易明細")
        print(f"{'='*80}")
        print(display_df.to_string(index=False))

        csv_path = reports_dir / f"value_investing_{timestamp}.csv"
        display_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"\n報告已輸出: {csv_path}")
    else:
        print("\n無任何交易紀錄")

    # 產出 HTML 權益曲線圖表（策略 vs 0050 基準）
    html_paths = []
    for sid, name, result in chart_data:
        # 正規化起始 = 100
        eq = result.equity_curve
        norm_eq = eq / eq.iloc[0] * 100

        norm_bench = None
        if bench:
            b_eq = bench["equity_curve"]
            # 對齊到策略的日期範圍
            common_start = eq.index[0]
            b_eq_aligned = b_eq[b_eq.index >= common_start]
            if not b_eq_aligned.empty:
                norm_bench = b_eq_aligned / b_eq_aligned.iloc[0] * 100

        fig = create_equity_curve(
            norm_eq,
            benchmark=norm_bench,
            drawdown=result.drawdown_curve if not result.drawdown_curve.empty else None,
            title=f"{sid} {name} 策略 vs 0050 (正規化=100)",
        )
        html_file = reports_dir / f"equity_{sid}_{timestamp}.html"
        fig.write_html(str(html_file))
        html_paths.append(html_file)
        logger.info(f"圖表已輸出: {html_file}")

    if html_paths:
        print(f"\n已產出 {len(html_paths)} 個 HTML 圖表於 reports/")
        webbrowser.open(html_paths[0].as_uri())

    # 績效摘要表（含 0050 基準行）
    if bench:
        results_summary.append({
            "stock_id": "0050",
            "name": "元大台灣50(基準)",
            "總報酬率(%)": round(bench["total_return"] * 100, 2),
            "年化報酬(%)": round(bench["annual_return"] * 100, 2),
            "Sharpe": bench["sharpe_ratio"],
            "最大回撤(%)": round(bench["max_drawdown"] * 100, 2),
            "勝率(%)": "N/A",
            "交易次數": "N/A",
        })

    if results_summary:
        summary_df = pd.DataFrame(results_summary)
        print(f"\n\n{'='*80}")
        print("  績效摘要")
        print(f"{'='*80}")
        print(summary_df.to_string(index=False))

        csv_summary = reports_dir / f"value_investing_summary_{timestamp}.csv"
        summary_df.to_csv(csv_summary, index=False, encoding="utf-8-sig")
        print(f"摘要已輸出: {csv_summary}")


if __name__ == "__main__":
    main()
