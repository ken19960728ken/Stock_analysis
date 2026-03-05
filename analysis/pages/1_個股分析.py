"""
Page 1: 個股分析 — 單股深度：K線、技術指標、籌碼、基本面
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

# 確保專案根目錄在 sys.path
ROOT = str(Path(__file__).resolve().parents[2])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from analysis.utils.charts import (
    create_candlestick_chart,
    create_chip_chart,
    create_fundamental_chart,
    create_margin_chart,
    create_short_sale_chart,
)
from analysis.utils.data_loader import (
    get_stock_options,
    load_chip_institutional,
    load_chip_margin,
    load_chip_securities_lending,
    load_chip_shareholding,
    load_chip_short_sale,
    load_daily_price,
    load_weekly_price,
    load_monthly_price,
    load_dividend_history,
    load_financial_reports,
    load_month_revenue,
    load_stock_per,
)
from analysis.utils.indicators import compute_all_indicators

st.set_page_config(page_title="個股分析", page_icon="📈", layout="wide")
st.title("📈 個股分析")

# --- Sidebar: 股票選擇 + 時間範圍 ---
stock_options = get_stock_options()
if not stock_options:
    st.warning("無法載入股票清單，請確認資料庫連線")
    st.stop()

selected_label = st.sidebar.selectbox("選擇股票", list(stock_options.keys()), index=0)
stock_id = stock_options[selected_label]

freq = st.sidebar.radio("K 線頻率", ["日K", "週K", "月K"], index=0, horizontal=True)

time_range = st.sidebar.radio("時間範圍", ["3M", "6M", "1Y", "3Y"], index=2, horizontal=True)
range_days = {"3M": 90, "6M": 180, "1Y": 365, "3Y": 1095}
start_date = (datetime.now() - timedelta(days=range_days[time_range])).strftime("%Y-%m-%d")

# --- 載入資料 ---
FREQ_LOADER = {"日K": load_daily_price, "週K": load_weekly_price, "月K": load_monthly_price}
FREQ_LABEL = {"日K": "日K", "週K": "週K", "月K": "月K"}
df = FREQ_LOADER[freq](stock_id, start_date=start_date)
if df.empty:
    st.warning(f"股票 {stock_id} 無{FREQ_LABEL[freq]}資料")
    st.stop()

# 計算技術指標
df = compute_all_indicators(df)

# --- Tab 1: 技術分析 | Tab 2: 籌碼分析 | Tab 3: 基本面 ---
tab1, tab2, tab3 = st.tabs(["📊 技術分析", "🏦 籌碼分析", "📋 基本面"])

with tab1:
    col1, col2 = st.columns([3, 1])
    with col2:
        # K 線類型
        candle_type = st.radio("K 線類型", ["一般 K 線", "Heikin-Ashi"], horizontal=True)
        # 均線選擇
        ma_options = st.multiselect("均線", [5, 10, 20, 60, 120, 240], default=[5, 20, 60])
        # 覆蓋指標
        show_bb = st.checkbox("Bollinger Bands", value=False)
        show_sar = st.checkbox("Parabolic SAR", value=False)
        # 副圖指標
        sub_indicators = st.multiselect("副圖指標", ["MACD", "RSI", "KD", "威廉", "AO"],
                                        default=["MACD"])

    with col1:
        fig = create_candlestick_chart(
            df,
            title=f"{selected_label}",
            ma_periods=ma_options,
            show_volume=True,
            show_bollinger=show_bb,
            show_sar=show_sar,
            heikin_ashi=(candle_type == "Heikin-Ashi"),
            indicators=sub_indicators,
        )
        st.plotly_chart(fig, use_container_width=True)

    # 最新數據摘要
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest
    change = latest["close"] - prev["close"]
    change_pct = change / prev["close"] * 100

    cols = st.columns(6)
    cols[0].metric("收盤價", f"{latest['close']:.2f}", f"{change:+.2f} ({change_pct:+.1f}%)")
    cols[1].metric("最高", f"{latest['high']:.2f}")
    cols[2].metric("最低", f"{latest['low']:.2f}")
    if "volume" in df.columns:
        cols[3].metric("成交量", f"{latest['volume']:,.0f}")
    if "RSI" in df.columns and not pd.isna(latest.get("RSI")):
        cols[4].metric("RSI(14)", f"{latest['RSI']:.1f}")
    if "K" in df.columns and not pd.isna(latest.get("K")):
        cols[5].metric("K / D", f"{latest['K']:.1f} / {latest.get('D', 0):.1f}")

with tab2:
    # 三大法人
    inst_df = load_chip_institutional(stock_id)
    if not inst_df.empty:
        st.subheader("三大法人買賣超")
        fig_chip = create_chip_chart(df, inst_df)
        st.plotly_chart(fig_chip, use_container_width=True)
    else:
        st.info("無三大法人資料")

    # 融資融券
    col_a, col_b = st.columns(2)
    with col_a:
        margin_df = load_chip_margin(stock_id)
        if not margin_df.empty:
            st.subheader("融資融券")
            fig_margin = create_margin_chart(margin_df)
            st.plotly_chart(fig_margin, use_container_width=True)
        else:
            st.info("無融資融券資料")

    with col_b:
        # 借券賣出
        short_df = load_chip_short_sale(stock_id)
        if not short_df.empty:
            st.subheader("借券賣出餘額")
            fig_short = create_short_sale_chart(short_df)
            st.plotly_chart(fig_short, use_container_width=True)
        else:
            st.info("無借券資料")

    # 股權分散表
    share_df = load_chip_shareholding(stock_id)
    if not share_df.empty:
        st.subheader("股權分散表")
        st.dataframe(share_df.tail(20), use_container_width=True)
    else:
        st.info("無股權分散表資料")

with tab3:
    fin_df = load_financial_reports(stock_id)
    rev_df = load_month_revenue(stock_id)
    per_df = load_stock_per(stock_id)
    div_df = load_dividend_history(stock_id)

    figs = create_fundamental_chart(fin_df, rev_df, per_df, div_df)

    col_a, col_b = st.columns(2)
    with col_a:
        if "eps" in figs:
            st.plotly_chart(figs["eps"], use_container_width=True)
        elif not fin_df.empty:
            st.subheader("財務報表")
            st.dataframe(fin_df.tail(20), use_container_width=True)
        else:
            st.info("無財務報表資料")

    with col_b:
        if "revenue" in figs:
            st.plotly_chart(figs["revenue"], use_container_width=True)
        elif not rev_df.empty:
            st.subheader("月營收")
            st.dataframe(rev_df.tail(20), use_container_width=True)
        else:
            st.info("無月營收資料")

    col_c, col_d = st.columns(2)
    with col_c:
        if "per" in figs:
            st.plotly_chart(figs["per"], use_container_width=True)
        elif not per_df.empty:
            st.subheader("本益比")
            st.dataframe(per_df.tail(20), use_container_width=True)
        else:
            st.info("無本益比資料")

    with col_d:
        if "dividend" in figs:
            st.plotly_chart(figs["dividend"], use_container_width=True)
        elif not div_df.empty:
            st.subheader("股利歷史")
            st.dataframe(div_df, use_container_width=True)
        else:
            st.info("無股利資料")
