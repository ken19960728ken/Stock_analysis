"""
Page 7: 策略組合 — 多策略組合回測與績效分析
"""

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = str(Path(__file__).resolve().parents[2])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from analysis.strategies import STRATEGY_MAP
from analysis.utils.data_loader import get_stock_options, load_daily_price
from analysis.utils.portfolio_backtester import PortfolioBacktester

st.set_page_config(page_title="策略組合", page_icon="📊", layout="wide")
st.title("📊 策略組合回測")

# --- Sidebar ---
st.sidebar.header("組合設定")

strategy_names = st.sidebar.multiselect(
    "選擇策略（至少 2 個）",
    list(STRATEGY_MAP.keys()),
    default=list(STRATEGY_MAP.keys())[:2],
)

stock_options = get_stock_options()
if stock_options:
    selected_label = st.sidebar.selectbox("選擇股票", list(stock_options.keys()))
    stock_id = stock_options[selected_label]
else:
    stock_id = st.sidebar.text_input("股票代號", value="2330")

col1, col2 = st.sidebar.columns(2)
start_date = col1.date_input("開始日期", value=pd.Timestamp("2022-01-01"))
end_date = col2.date_input("結束日期", value=pd.Timestamp.now())

WEIGHT_METHODS = {
    "等權分配": "equal",
    "Sharpe 最大化": "max_sharpe",
    "最小波動率": "min_volatility",
    "風險平價": "risk_parity",
}
weight_mode = st.sidebar.radio("權重模式", list(WEIGHT_METHODS.keys()))
weight_method = WEIGHT_METHODS[weight_mode]

run_btn = st.sidebar.button("執行組合回測", type="primary")

# --- Main ---
if len(strategy_names) < 2:
    st.warning("請至少選擇 2 個策略")
    st.stop()

if run_btn:
    with st.spinner("執行策略組合回測中..."):
        data = load_daily_price(stock_id, str(start_date), str(end_date))

        if data.empty:
            st.error("無法載入股價資料")
            st.stop()

        strategies = []
        for name in strategy_names:
            cls = STRATEGY_MAP[name]
            strategies.append(cls())

        pb = PortfolioBacktester(strategies=strategies)
        result = pb.run(data, weight_method=weight_method)

    # --- Section 1: 策略績效對比表 ---
    st.subheader("策略績效對比")
    perf_rows = []
    for name, res in result.strategy_results.items():
        perf_rows.append({
            "策略": name,
            "總報酬率": f"{res.total_return:.2%}",
            "年化報酬": f"{res.annual_return:.2%}",
            "Sharpe": f"{res.sharpe_ratio:.2f}",
            "Sortino": f"{res.sortino_ratio:.2f}",
            "最大回撤": f"{res.max_drawdown:.2%}",
            "勝率": f"{res.win_rate:.2%}",
            "交易次數": res.trade_count,
        })
    if perf_rows:
        st.dataframe(pd.DataFrame(perf_rows), use_container_width=True)

    # --- Section 2: 策略相關性矩陣 ---
    if not result.correlation_matrix.empty:
        st.subheader("策略報酬相關性矩陣")
        fig_corr = px.imshow(
            result.correlation_matrix,
            text_auto=".2f",
            color_continuous_scale="RdBu_r",
            zmin=-1, zmax=1,
        )
        fig_corr.update_layout(height=400)
        st.plotly_chart(fig_corr, use_container_width=True)

    # --- Section 3: 權益曲線疊圖 ---
    st.subheader("權益曲線")
    fig_eq = go.Figure()
    for name, res in result.strategy_results.items():
        if not res.equity_curve.empty:
            fig_eq.add_trace(go.Scatter(
                x=res.equity_curve.index, y=res.equity_curve.values,
                mode="lines", name=name, opacity=0.7,
            ))
    if not result.combined_equity.empty:
        fig_eq.add_trace(go.Scatter(
            x=result.combined_equity.index, y=result.combined_equity.values,
            mode="lines", name="組合", line=dict(width=3, dash="dash"),
        ))
    fig_eq.update_layout(
        height=500,
        yaxis_title="權益 (TWD)",
        xaxis_title="日期",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig_eq, use_container_width=True)

    # --- Section 4: 組合績效指標 ---
    st.subheader("組合績效")
    c1, c2 = st.columns(2)
    c1.metric("組合總報酬率", f"{result.combined_return:.2%}")
    c2.metric("組合 Sharpe Ratio", f"{result.combined_sharpe:.2f}")

    # --- Section 5: 權重分配 ---
    st.subheader("權重分配")
    if result.weights:
        w_df = pd.DataFrame([
            {"策略": k, "權重": v} for k, v in result.weights.items()
        ])
        fig_w = px.bar(w_df, x="策略", y="權重", text_auto=".2%")
        fig_w.update_layout(height=350, yaxis_title="權重")
        st.plotly_chart(fig_w, use_container_width=True)

    # --- Section 6: 風險貢獻 ---
    if result.risk_contributions:
        st.subheader("風險貢獻")
        rc_df = pd.DataFrame([
            {"策略": k, "風險貢獻": v} for k, v in result.risk_contributions.items()
        ])
        fig_rc = px.pie(rc_df, values="風險貢獻", names="策略",
                        title="各策略風險貢獻占比")
        fig_rc.update_layout(height=350)
        st.plotly_chart(fig_rc, use_container_width=True)
