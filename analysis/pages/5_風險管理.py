"""
Page 5: 風險管理 — 持倉監控、VaR、回撤分析、部位管理
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = str(Path(__file__).resolve().parents[2])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from analysis.utils.charts import create_correlation_heatmap, create_equity_curve
from analysis.utils.data_loader import get_stock_options, load_daily_price, load_industry_mapping
from analysis.utils.risk import (
    calc_beta,
    calc_calmar_ratio,
    calc_cvar,
    calc_industry_concentration,
    calc_max_drawdown,
    calc_sharpe,
    calc_sortino,
    calc_var,
)

st.set_page_config(page_title="風險管理", page_icon="🛡️", layout="wide")
st.title("🛡️ 風險管理")

# --- 持倉輸入 ---
st.sidebar.header("持倉管理")
st.sidebar.info("輸入你的持倉資訊進行風險分析")

stock_options = get_stock_options()
if not stock_options:
    st.warning("無法載入股票清單")
    st.stop()

# 使用 session_state 管理持倉
if "holdings" not in st.session_state:
    st.session_state.holdings = []

with st.sidebar.form("add_holding"):
    st.subheader("新增持倉")
    sel = st.selectbox("股票", list(stock_options.keys()))
    shares = st.number_input("股數", min_value=0, value=1000, step=1000)
    cost = st.number_input("成本價", min_value=0.0, value=100.0, step=1.0)
    submitted = st.form_submit_button("新增")
    if submitted and shares > 0:
        st.session_state.holdings.append({
            "stock_id": stock_options[sel],
            "name": sel,
            "shares": shares,
            "cost_price": cost,
        })

if st.sidebar.button("清除全部持倉"):
    st.session_state.holdings = []

# 顯示持倉
if not st.session_state.holdings:
    st.info("👈 請在左側新增持倉，或使用以下範例")
    if st.button("載入範例持倉"):
        example_options = list(stock_options.keys())
        if len(example_options) >= 3:
            st.session_state.holdings = [
                {"stock_id": stock_options[example_options[0]], "name": example_options[0],
                 "shares": 1000, "cost_price": 500},
                {"stock_id": stock_options[example_options[1]], "name": example_options[1],
                 "shares": 2000, "cost_price": 100},
                {"stock_id": stock_options[example_options[2]], "name": example_options[2],
                 "shares": 5000, "cost_price": 30},
            ]
            st.rerun()
    st.stop()

holdings_df = pd.DataFrame(st.session_state.holdings)

# --- 載入價格資料 ---
start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
price_data = {}
current_prices = {}
returns_dict = {}

with st.spinner("載入價格資料..."):
    for sid in holdings_df["stock_id"].unique():
        pdf = load_daily_price(sid, start_date=start_date)
        if not pdf.empty:
            price_data[sid] = pdf
            current_prices[sid] = pdf["close"].iloc[-1]
            returns_dict[sid] = pdf.set_index("date")["close"].pct_change().dropna()
        else:
            current_prices[sid] = holdings_df.loc[
                holdings_df["stock_id"] == sid, "cost_price"
            ].values[0]

# --- 持倉總覽 ---
st.header("持倉總覽")
positions = []
for _, row in holdings_df.iterrows():
    sid = row["stock_id"]
    current = current_prices.get(sid, row["cost_price"])
    mv = row["shares"] * current
    pnl = (current - row["cost_price"]) * row["shares"]
    pnl_pct = (current / row["cost_price"] - 1) * 100 if row["cost_price"] > 0 else 0
    positions.append({
        "標的": row["name"],
        "股數": row["shares"],
        "成本價": row["cost_price"],
        "現價": round(current, 2),
        "市值": round(mv, 0),
        "損益": round(pnl, 0),
        "損益%": round(pnl_pct, 2),
    })

positions_df = pd.DataFrame(positions)
total_value = positions_df["市值"].sum()
total_cost = sum(r["shares"] * r["cost_price"] for _, r in holdings_df.iterrows())
total_pnl = total_value - total_cost
total_pnl_pct = (total_value / total_cost - 1) * 100 if total_cost > 0 else 0

cols = st.columns(4)
cols[0].metric("總市值", f"${total_value:,.0f}")
cols[1].metric("總損益", f"${total_pnl:,.0f}", f"{total_pnl_pct:+.1f}%")
cols[2].metric("持股檔數", f"{len(holdings_df)}")
cols[3].metric("總成本", f"${total_cost:,.0f}")

st.dataframe(positions_df, use_container_width=True)

# --- 風險指標 ---
st.header("風險指標")

if returns_dict:
    returns_df = pd.DataFrame(returns_dict).dropna()
    if not returns_df.empty and len(returns_df) > 5:
        # 計算投資組合權重和報酬
        weights = np.array([
            holdings_df.loc[holdings_df["stock_id"] == sid, "shares"].values[0]
            * current_prices.get(sid, 0)
            for sid in returns_df.columns
        ])
        weight_sum = weights.sum()
        if weight_sum > 0:
            weights = weights / weight_sum
        port_returns = returns_df.dot(weights)

        var_95 = calc_var(port_returns, 0.95)
        cvar_95 = calc_cvar(port_returns, 0.95)
        sharpe = calc_sharpe(port_returns)
        sortino = calc_sortino(port_returns)
        from core.constants import TRADING_DAYS_PER_YEAR
        volatility = port_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)

        cols = st.columns(5)
        cols[0].metric("VaR (95%)", f"{var_95 * 100:.2f}%")
        cols[1].metric("CVaR (95%)", f"{cvar_95 * 100:.2f}%")
        cols[2].metric("Sharpe Ratio", f"{sharpe:.2f}")
        cols[3].metric("Sortino Ratio", f"{sortino:.2f}")
        cols[4].metric("年化波動率", f"{volatility * 100:.1f}%")

        # --- 回撤分析 ---
        st.header("回撤分析")
        equity = (1 + port_returns).cumprod() * total_cost
        max_dd, dd_series, peak_date, trough_date, dd_days = calc_max_drawdown(equity)

        cols = st.columns(3)
        cols[0].metric("最大回撤", f"{max_dd * 100:.1f}%")
        cols[1].metric("回撤持續天數", f"{dd_days}")
        annual_return = port_returns.mean() * TRADING_DAYS_PER_YEAR
        cols[2].metric("Calmar Ratio", f"{calc_calmar_ratio(annual_return, max_dd):.2f}")

        # 水下權益曲線
        fig_dd = create_equity_curve(
            equity, drawdown=dd_series, title="投資組合權益曲線"
        )
        st.plotly_chart(fig_dd, use_container_width=True)

        # --- 相關性矩陣 ---
        st.header("持倉相關性矩陣")
        if returns_df.shape[1] > 1:
            corr = returns_df.corr()
            # 使用股票名稱替換 stock_id
            name_map = dict(zip(holdings_df["stock_id"], holdings_df["name"]))
            corr.columns = [name_map.get(c, c) for c in corr.columns]
            corr.index = [name_map.get(c, c) for c in corr.index]
            fig_corr = create_correlation_heatmap(corr, "持倉間相關性")
            st.plotly_chart(fig_corr, use_container_width=True)

            # 集中度警示
            max_weight = weights.max()
            if max_weight > 0.5:
                st.warning(f"⚠️ 單一持倉佔比 {max_weight * 100:.0f}% 超過 50%，集中度過高")
        else:
            st.info("僅一支持股，無法計算相關性")

        # --- 報酬分佈 ---
        st.header("日報酬分佈")
        fig_dist = go.Figure()
        fig_dist.add_trace(go.Histogram(
            x=port_returns, nbinsx=50, name="日報酬",
            marker_color="#4FC3F7",
        ))
        fig_dist.add_vline(x=var_95, line_dash="dash", line_color="red",
                            annotation_text=f"VaR 95%: {var_95 * 100:.2f}%")
        fig_dist.update_layout(
            title="投資組合日報酬分佈", template="plotly_dark", height=350,
            xaxis_title="日報酬率", yaxis_title="頻率",
        )
        st.plotly_chart(fig_dist, use_container_width=True)

        # --- 產業集中度 ---
        st.header("產業集中度")
        ind_map = load_industry_mapping()
        if not ind_map.empty:
            conc = calc_industry_concentration(holdings_df, current_prices, ind_map)
            breakdown = conc["breakdown"]
            if not breakdown.empty:
                import plotly.express as px
                fig_pie = px.pie(
                    breakdown, values="weight", names="sector",
                    title="持倉產業分佈",
                    color_discrete_sequence=px.colors.qualitative.Set3,
                )
                fig_pie.update_layout(template="plotly_dark", height=400)
                st.plotly_chart(fig_pie, use_container_width=True)

                # HHI 指標
                hhi = conc["hhi"]
                hhi_label = "高度集中" if hhi > 0.25 else ("中度集中" if hhi > 0.15 else "分散")
                st.metric("HHI 集中度指數", f"{hhi:.4f}", hhi_label)

                # 警告
                for w in conc["warnings"]:
                    st.warning(f"⚠️ {w}")

                # 明細表
                bd = breakdown.copy()
                bd["market_value"] = bd["market_value"].map(lambda x: f"${x:,.0f}")
                bd["weight"] = bd["weight"].map(lambda x: f"{x:.1%}")
                st.dataframe(bd.rename(columns={"sector": "產業", "market_value": "市值", "weight": "佔比"}),
                             use_container_width=True, hide_index=True)
        else:
            st.info("無產業分類資料，請先執行 `python main.py --scanner industry`")

    else:
        st.warning("報酬率資料不足，無法計算風險指標")
else:
    st.warning("無法載入價格資料")
