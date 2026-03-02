"""
Page 3: 策略回測 — 內建策略 + 績效報告
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

ROOT = str(Path(__file__).resolve().parents[2])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from analysis.strategies import STRATEGY_MAP
from analysis.utils.backtester import Backtester
from analysis.utils.charts import (
    create_candlestick_chart,
    create_equity_curve,
    create_monthly_heatmap,
)
from analysis.utils.data_loader import (
    get_stock_options,
    load_daily_price,
    load_chip_institutional,
    load_chip_margin,
    load_chip_holding_pct,
    load_financial_reports,
    load_market_value,
    load_month_revenue,
    load_stock_per,
)

# 各策略所需的補充資料表
# 注意：「股權集中度」策略需要 shareholder_count，
# 實際資料在 chip_holding_pct 表（people 欄位），而非 chip_shareholding。
STRATEGY_DATA_NEEDS = {
    "法人跟單": ["chip_institutional"],
    "融資融券訊號": ["chip_margin"],
    "股權集中度": ["chip_holding_pct"],
    "財報三率": ["financial_reports"],
    "自由現金流": ["financial_reports", "market_value"],
    "價值投資": ["stock_per", "month_revenue"],
    "多因子綜合": ["chip_institutional", "stock_per"],
}


def _enrich_data(df: pd.DataFrame, stock_id: str, strategy_name: str) -> pd.DataFrame:
    """根據策略需求載入補充資料並合併到 daily_price"""
    needs = STRATEGY_DATA_NEEDS.get(strategy_name, [])
    if not needs:
        return df

    df = df.sort_values("date").copy()

    for table in needs:
        if table == "chip_institutional":
            extra = load_chip_institutional(stock_id)
            if not extra.empty:
                # 計算三大法人淨買超（策略需要正=買超、負=賣超的單一欄位）
                buy_cols = [c for c in extra.columns if c.endswith("_buy")]
                sell_cols = [c for c in extra.columns if c.endswith("_sell")]
                if buy_cols and sell_cols:
                    extra["institutional_net_buy"] = (
                        extra[buy_cols].sum(axis=1) - extra[sell_cols].sum(axis=1)
                    )
                # 只保留 date + net_buy，避免策略誤匹配原始 buy 欄位
                keep = ["date", "institutional_net_buy"]
                extra = extra[[c for c in keep if c in extra.columns]]
                df = df.merge(extra, on="date", how="left")

        elif table == "chip_margin":
            extra = load_chip_margin(stock_id)
            if not extra.empty:
                extra = extra.drop(columns=["stock_id"], errors="ignore")
                df = df.merge(extra, on="date", how="left")

        elif table == "chip_holding_pct":
            extra = load_chip_holding_pct(stock_id)
            if not extra.empty:
                # chip_holding_pct 表每日有多筆（不同持股級距），
                # 欄位: date, stock_id, HoldingSharesLevel, people, percent, unit
                # 聚合為每日一筆：
                #   shareholder_count = sum(people)  — 總股東人數
                #   holding_percentage = sum(percent) — 總持股比例
                agg = extra.groupby("date").agg(
                    shareholder_count=("people", "sum"),
                    holding_percentage=("percent", "sum"),
                ).reset_index().sort_values("date")
                df = pd.merge_asof(df, agg, on="date", direction="backward")

        elif table == "financial_reports":
            extra = load_financial_reports(stock_id)
            if not extra.empty and "type" in extra.columns:
                pivoted = extra.pivot_table(
                    index="date", columns="type", values="value", aggfunc="first",
                ).reset_index()
                pivoted.columns.name = None
                pivoted = pivoted.sort_values("date")
                df = pd.merge_asof(df, pivoted, on="date", direction="backward")

        elif table == "market_value":
            extra = load_market_value(stock_id)
            if not extra.empty:
                mv_cols = ["date"] + [c for c in extra.columns if c not in ("date", "stock_id")]
                extra = extra[mv_cols].sort_values("date")
                df = pd.merge_asof(df, extra, on="date", direction="backward")

        elif table == "stock_per":
            extra = load_stock_per(stock_id)
            if not extra.empty:
                extra = extra.drop(columns=["stock_id"], errors="ignore")
                extra = extra.sort_values("date")
                df = pd.merge_asof(df, extra, on="date", direction="backward")

        elif table == "month_revenue":
            extra = load_month_revenue(stock_id)
            if not extra.empty:
                extra = extra.drop(columns=["stock_id"], errors="ignore").sort_values("date")
                df = pd.merge_asof(df, extra, on="date", direction="backward")

    return df

st.set_page_config(page_title="策略回測", page_icon="🧪", layout="wide")
st.title("🧪 策略回測")

# --- Sidebar ---
st.sidebar.header("回測設定")

# 股票選擇
stock_options = get_stock_options()
if not stock_options:
    st.warning("無法載入股票清單")
    st.stop()
selected_label = st.sidebar.selectbox("選擇股票", list(stock_options.keys()), index=0)
stock_id = stock_options[selected_label]

# 策略選擇
strategy_name = st.sidebar.selectbox("選擇策略", list(STRATEGY_MAP.keys()))
strategy_cls = STRATEGY_MAP[strategy_name]
strategy = strategy_cls()

# 策略參數
st.sidebar.subheader("策略參數")
params = strategy.get_params()
updated_params = {}
for k, v in params.items():
    if isinstance(v, int):
        updated_params[k] = st.sidebar.number_input(k, value=v, step=1)
    elif isinstance(v, float):
        updated_params[k] = st.sidebar.number_input(k, value=v, step=0.01, format="%.2f")
    else:
        updated_params[k] = st.sidebar.text_input(k, value=str(v))
strategy.set_params(**updated_params)

# 回測期間
col_start, col_end = st.sidebar.columns(2)
with col_start:
    start_date = st.date_input("開始日期", datetime.now() - timedelta(days=365))
with col_end:
    end_date = st.date_input("結束日期", datetime.now())

# 資金設定
initial_capital = st.sidebar.number_input("初始資金", value=1_000_000, step=100_000)
commission = st.sidebar.number_input("手續費率", value=0.001425, format="%.6f")
tax = st.sidebar.number_input("證交稅率", value=0.003, format="%.4f")
slippage = st.sidebar.number_input("滑價", value=0.001, format="%.4f")

# 執行回測
run_bt = st.sidebar.button("🚀 執行回測", type="primary", use_container_width=True)

if run_bt:
    with st.spinner("回測中..."):
        df = load_daily_price(stock_id, str(start_date), str(end_date))
        if df.empty:
            st.error("無法載入價格資料")
            st.stop()

        # 根據策略需求載入補充資料（籌碼、財報等）
        df = _enrich_data(df, stock_id, strategy_name)

        backtester = Backtester(
            strategy=strategy,
            capital=initial_capital,
            commission=commission,
            tax=tax,
            slippage=slippage,
        )
        result = backtester.run(df)

        # 計算 0050 買入持有基準
        bench_info = None
        bench_df = load_daily_price("0050", str(start_date), str(end_date))
        if not bench_df.empty and len(bench_df) >= 2:
            b_commission = 0.001425
            b_first_close = bench_df.iloc[0]["close"]
            b_shares = int(initial_capital / (b_first_close * (1 + b_commission)) / 1000) * 1000
            if b_shares > 0:
                b_cost = b_shares * b_first_close * (1 + b_commission)
                b_cash = initial_capital - b_cost
                b_equity_vals = b_cash + b_shares * bench_df["close"].values
                b_equity = pd.Series(b_equity_vals, index=bench_df["date"])

                b_total_return = (b_equity.iloc[-1] / initial_capital) - 1
                b_days = (b_equity.index[-1] - b_equity.index[0]).days
                b_annual = (1 + b_total_return) ** (365 / b_days) - 1 if b_days > 0 else 0.0
                b_returns = b_equity.pct_change().dropna()
                from core.constants import RISK_FREE_RATE, TRADING_DAYS_PER_YEAR
                rf = RISK_FREE_RATE
                if len(b_returns) > 1 and b_returns.std() > 1e-12:
                    b_sharpe = (b_returns.mean() - rf / TRADING_DAYS_PER_YEAR) / b_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
                else:
                    b_sharpe = 0.0
                b_peak = b_equity.cummax()
                b_dd = (b_equity - b_peak) / b_peak
                b_max_dd = b_dd.min()

                bench_info = {
                    "equity_curve": b_equity,
                    "total_return": b_total_return,
                    "annual_return": b_annual,
                    "sharpe_ratio": round(b_sharpe, 2),
                    "max_drawdown": b_max_dd,
                }

    st.success(f"回測完成: {strategy.name} on {selected_label}")

    # --- 績效指標卡片 ---
    st.subheader("績效總覽")
    cols = st.columns(5)
    cols[0].metric("總報酬率", f"{result.total_return * 100:+.1f}%")
    cols[1].metric("年化報酬率", f"{result.annual_return * 100:+.1f}%")
    cols[2].metric("Sharpe Ratio", f"{result.sharpe_ratio:.2f}")
    cols[3].metric("最大回撤", f"{result.max_drawdown * 100:.1f}%")
    cols[4].metric("交易次數", f"{result.trade_count}")

    cols2 = st.columns(5)
    cols2[0].metric("勝率", f"{result.win_rate * 100:.1f}%")
    cols2[1].metric("獲利因子", f"{result.profit_factor:.2f}")
    cols2[2].metric("Sortino Ratio", f"{result.sortino_ratio:.2f}")
    cols2[3].metric("回撤持續天數", f"{result.max_drawdown_duration}")
    cols2[4].metric("平均持有天數", f"{result.avg_holding_days:.0f}")

    # --- 0050 基準指標 ---
    if bench_info:
        st.subheader("0050 買入持有基準")
        bcols = st.columns(4)
        bcols[0].metric("0050 總報酬率", f"{bench_info['total_return'] * 100:+.1f}%")
        bcols[1].metric("0050 年化報酬", f"{bench_info['annual_return'] * 100:+.1f}%")
        bcols[2].metric("0050 Sharpe", f"{bench_info['sharpe_ratio']:.2f}")
        bcols[3].metric("0050 最大回撤", f"{bench_info['max_drawdown'] * 100:.1f}%")

    # --- 權益曲線 ---
    st.subheader("權益曲線")
    if not result.equity_curve.empty:
        bench_equity = bench_info["equity_curve"] if bench_info else None
        fig_equity = create_equity_curve(
            result.equity_curve,
            benchmark=bench_equity,
            drawdown=result.drawdown_curve if not result.drawdown_curve.empty else None,
            title=f"{strategy.name} 權益曲線 — {selected_label}",
        )
        st.plotly_chart(fig_equity, use_container_width=True)

    # --- K 線圖 + 交易標記 ---
    st.subheader("交易標記")
    if not result.trades.empty:
        # 整理交易標記資料
        trade_marks = []
        for _, t in result.trades.iterrows():
            trade_marks.append({"date": t["entry_date"], "action": "buy", "price": t["entry_price"]})
            trade_marks.append({"date": t["exit_date"], "action": "sell", "price": t["exit_price"]})
        trades_df = pd.DataFrame(trade_marks)

        from analysis.utils.indicators import add_ma
        df_with_ma = add_ma(df.copy())
        fig_trades = create_candlestick_chart(
            df_with_ma,
            title=f"{strategy.name} 交易記錄",
            ma_periods=[5, 20],
            show_volume=True,
            trades=trades_df,
        )
        st.plotly_chart(fig_trades, use_container_width=True)

    # --- 月報酬率熱力圖 ---
    if not result.monthly_returns.empty:
        st.subheader("月報酬率")
        fig_monthly = create_monthly_heatmap(result.monthly_returns)
        st.plotly_chart(fig_monthly, use_container_width=True)

    # --- 交易明細 ---
    st.subheader("交易明細")
    if not result.trades.empty:
        display_trades = result.trades.copy()
        display_trades.columns = ["進場日期", "出場日期", "進場價", "出場價",
                                   "股數", "損益", "損益%", "持有天數"]
        st.dataframe(display_trades, use_container_width=True)

        csv = display_trades.to_csv(index=False)
        st.download_button("📥 匯出交易明細", csv, "trades.csv", "text/csv")
    else:
        st.info("此期間無交易訊號")

else:
    # 尚未執行回測，顯示策略說明
    st.info("👈 請在左側選擇策略和標的，點擊「執行回測」開始")

    st.subheader("內建策略一覽")
    strategy_info = []
    for name, cls in STRATEGY_MAP.items():
        s = cls()
        strategy_info.append({
            "策略名稱": name,
            "說明": s.description,
            "參數": str(s.get_params()),
        })
    st.dataframe(pd.DataFrame(strategy_info), use_container_width=True)
