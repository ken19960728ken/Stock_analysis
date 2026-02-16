"""
Page 4: 配對交易 — 共整合檢定、統計套利、價差監控
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

ROOT = str(Path(__file__).resolve().parents[2])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from analysis.utils.charts import create_correlation_heatmap
from analysis.utils.data_loader import get_stock_options, load_daily_price
from analysis.utils.pair_trading import (
    calc_half_life,
    calc_spread,
    calc_zscore,
    engle_granger_test,
    pair_trading_signals,
)

st.set_page_config(page_title="配對交易", page_icon="🔗", layout="wide")
st.title("🔗 配對交易（統計套利）")

# --- Step 1: 選擇配對 ---
st.sidebar.header("配對設定")
stock_options = get_stock_options()
if not stock_options:
    st.warning("無法載入股票清單")
    st.stop()

options_list = list(stock_options.keys())
stock_a_label = st.sidebar.selectbox("股票 A (Y)", options_list, index=0)
stock_b_label = st.sidebar.selectbox("股票 B (X)",
                                      options_list,
                                      index=min(1, len(options_list) - 1))

stock_a = stock_options[stock_a_label]
stock_b = stock_options[stock_b_label]

# 期間
lookback = st.sidebar.selectbox("回溯期間", ["6M", "1Y", "2Y", "3Y"], index=1)
lookback_days = {"6M": 180, "1Y": 365, "2Y": 730, "3Y": 1095}
start_date = (datetime.now() - timedelta(days=lookback_days[lookback])).strftime("%Y-%m-%d")

# Z-Score 參數
zscore_window = st.sidebar.slider("Z-Score 移動視窗", 10, 60, 20)
entry_z = st.sidebar.slider("進場 Z-Score", 1.0, 3.0, 2.0, step=0.1)
exit_z = st.sidebar.slider("出場 Z-Score", 0.0, 1.5, 0.5, step=0.1)

run_analysis = st.sidebar.button("🔍 分析配對", type="primary", use_container_width=True)

if run_analysis:
    if stock_a == stock_b:
        st.error("請選擇兩支不同的股票")
        st.stop()

    with st.spinner("載入資料..."):
        df_a = load_daily_price(stock_a, start_date=start_date)
        df_b = load_daily_price(stock_b, start_date=start_date)

    if df_a.empty or df_b.empty:
        st.error("無法載入一或兩支股票的價格資料")
        st.stop()

    # 對齊日期
    price_a = df_a.set_index("date")["close"]
    price_b = df_b.set_index("date")["close"]
    aligned = pd.concat([price_a, price_b], axis=1, keys=[stock_a, stock_b]).dropna()

    if len(aligned) < 60:
        st.warning("共同交易日不足 60 天")
        st.stop()

    y = aligned[stock_a]
    x = aligned[stock_b]

    # --- Step 2: 共整合檢定 ---
    st.header("Step 1: 共整合檢定")
    with st.spinner("執行 Engle-Granger 檢定..."):
        eg_result = engle_granger_test(y, x)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("ADF 統計量", f"{eg_result['adf_stat']:.4f}")
    col2.metric("p-value", f"{eg_result['p_value']:.4f}")
    col3.metric("Beta", f"{eg_result['beta']:.4f}")
    col4.metric("R²", f"{eg_result['r_squared']:.4f}")

    if eg_result["is_cointegrated"]:
        st.success("✅ 共整合成立 (p < 0.05) — 可進行配對交易")
    else:
        st.warning("⚠️ 共整合不成立 (p >= 0.05) — 需謹慎")

    # 臨界值
    with st.expander("ADF 臨界值"):
        for level, value in eg_result["critical_values"].items():
            st.write(f"{level}: {value:.4f}")

    # --- 價差 & Z-Score ---
    st.header("Step 2: 價差分析")
    spread = calc_spread(y, x, eg_result["beta"], eg_result["intercept"])
    zscore = calc_zscore(spread, zscore_window)
    half_life = calc_half_life(spread)

    st.metric("半衰期", f"{half_life:.1f} 天" if half_life < 1000 else "不收斂")

    # 價差走勢圖
    fig_spread = make_subplots(rows=2, cols=1, shared_xaxes=True,
                                vertical_spacing=0.05,
                                subplot_titles=["價差 (Spread)", "Z-Score"],
                                row_heights=[0.5, 0.5])

    fig_spread.add_trace(
        go.Scatter(x=spread.index, y=spread, name="Spread",
                   line=dict(color="#4FC3F7")),
        row=1, col=1,
    )
    mean_spread = spread.mean()
    std_spread = spread.std()
    fig_spread.add_hline(y=mean_spread, line_dash="dash", line_color="white", row=1, col=1)
    fig_spread.add_hline(y=mean_spread + 2 * std_spread, line_dash="dot",
                          line_color="red", row=1, col=1)
    fig_spread.add_hline(y=mean_spread - 2 * std_spread, line_dash="dot",
                          line_color="green", row=1, col=1)

    # Z-Score
    fig_spread.add_trace(
        go.Scatter(x=zscore.index, y=zscore, name="Z-Score",
                   line=dict(color="#BA68C8")),
        row=2, col=1,
    )
    fig_spread.add_hline(y=entry_z, line_dash="dash", line_color="red", row=2, col=1)
    fig_spread.add_hline(y=-entry_z, line_dash="dash", line_color="green", row=2, col=1)
    fig_spread.add_hline(y=exit_z, line_dash="dot", line_color="gray", row=2, col=1)
    fig_spread.add_hline(y=-exit_z, line_dash="dot", line_color="gray", row=2, col=1)
    fig_spread.add_hline(y=0, line_dash="solid", line_color="white",
                          opacity=0.3, row=2, col=1)

    fig_spread.update_layout(template="plotly_dark", height=600)
    st.plotly_chart(fig_spread, use_container_width=True)

    # --- Step 3: 交易訊號 ---
    st.header("Step 3: 配對交易訊號")
    signals = pair_trading_signals(spread, entry_z, exit_z, window=zscore_window)

    # 正規化價格比較
    fig_pair = go.Figure()
    norm_a = y / y.iloc[0] * 100
    norm_b = x / x.iloc[0] * 100
    fig_pair.add_trace(
        go.Scatter(x=norm_a.index, y=norm_a, name=f"{stock_a} (正規化)",
                   line=dict(color="#4FC3F7"))
    )
    fig_pair.add_trace(
        go.Scatter(x=norm_b.index, y=norm_b, name=f"{stock_b} (正規化)",
                   line=dict(color="#FFA726"))
    )

    # 標記進出場
    entries = signals.diff()
    long_entries = entries[entries == 1].index
    short_entries = entries[entries == -1].index
    exits = entries[(entries.shift(1) != 0) & (entries == 0)].index

    for dt in long_entries:
        fig_pair.add_vline(x=dt, line_dash="dash", line_color="green", opacity=0.5)
    for dt in short_entries:
        fig_pair.add_vline(x=dt, line_dash="dash", line_color="red", opacity=0.5)

    fig_pair.update_layout(
        title="正規化價格比較 (100 基準)",
        template="plotly_dark", height=400,
    )
    st.plotly_chart(fig_pair, use_container_width=True)

    # 相關性
    st.header("相關性")
    corr = aligned.corr()
    st.metric("Pearson 相關係數", f"{corr.iloc[0, 1]:.4f}")

    # 提示
    st.info("⚠️ **重要提醒**: 歷史共整合不保證未來穩定。建議設定共整合崩壞的停損機制，"
            "並定期重新檢定。")

else:
    st.info("👈 請在左側選擇兩支股票，點擊「分析配對」開始")

    st.markdown("""
    ### 配對交易流程
    1. **候選配對篩選** — 選擇同產業或高相關的股票
    2. **共整合檢定** — Engle-Granger 兩步法確認關係
    3. **價差監控** — Z-Score 追蹤偏離程度
    4. **交易執行** — Z > 2σ 進場，Z < 0.5σ 出場
    """)
