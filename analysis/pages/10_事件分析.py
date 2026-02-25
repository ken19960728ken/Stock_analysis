"""
Page 10: 事件分析 — 除息/財報事件研究、CAR/AAR 分析、事件策略回測
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = str(Path(__file__).resolve().parents[2])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from analysis.utils.backtester import Backtester
from analysis.utils.data_loader import (
    load_daily_price_all,
    load_dividend_events_all,
    load_earnings_dates_all,
    load_top_volume_stocks,
)
from analysis.utils.event_study import (
    EventStudyResult,
    calc_abnormal_returns,
    event_trading_signals,
    extract_events,
)

st.set_page_config(page_title="事件分析", page_icon="📅", layout="wide")
st.title("📅 事件分析")

# --- Sidebar ---
st.sidebar.header("分析設定")

event_type = st.sidebar.radio("事件類型", ["除息事件", "財報公布"])
event_type_key = "dividend" if event_type == "除息事件" else "earnings"

pool_option = st.sidebar.radio("股票池", ["成交量前 50", "自選"], key="event_pool")
if pool_option == "自選":
    custom_ids = st.sidebar.text_area(
        "輸入股票代號（逗號分隔）",
        value="2330,2317,2454,2881,2882",
        key="event_custom_ids",
    )
    stock_ids = [s.strip() for s in custom_ids.split(",") if s.strip()]
else:
    stock_ids = load_top_volume_stocks(n=50, lookback_days=30)

window_before = st.sidebar.slider("事件前窗口（天）", 1, 30, 10)
window_after = st.sidebar.slider("事件後窗口（天）", 1, 60, 20)
model = st.sidebar.selectbox("異常報酬模型", ["市場調整", "均值回歸"])
model_key = "market_adjusted" if model == "市場調整" else "mean_return"

run_btn = st.sidebar.button("執行分析", type="primary", use_container_width=True)

# --- Main ---
if run_btn:
    if not stock_ids:
        st.error("股票池為空。")
        st.stop()

    with st.spinner("載入資料中..."):
        start_date = (date.today() - timedelta(days=730)).isoformat()
        price_df = load_daily_price_all(start_date)
        price_df = price_df[price_df["stock_id"].isin(stock_ids)]

        if event_type_key == "dividend":
            event_source = load_dividend_events_all(start_date)
        else:
            event_source = load_earnings_dates_all(start_date)

        event_source = event_source[event_source["stock_id"].isin(stock_ids)]

    if price_df.empty:
        st.error("無法載入價格資料。")
        st.stop()

    if event_source.empty:
        st.error(f"無 {event_type} 資料。")
        st.stop()

    with st.spinner("計算異常報酬..."):
        events = extract_events(event_source, event_type_key)
        es_result = calc_abnormal_returns(
            price_df, events,
            window_before=window_before,
            window_after=window_after,
            model=model_key,
        )

    st.session_state["es_result"] = es_result
    st.session_state["es_price_df"] = price_df
    st.session_state["es_events"] = events
    st.session_state["es_params"] = {
        "window_before": window_before,
        "window_after": window_after,
        "event_type": event_type,
    }

if "es_result" not in st.session_state:
    st.info("請在左側面板設定參數後，點擊「執行分析」。")
    st.stop()

es_result = st.session_state["es_result"]
price_df = st.session_state["es_price_df"]
events = st.session_state["es_events"]
params = st.session_state["es_params"]

tab1, tab2, tab3 = st.tabs(["📈 CAR/AAR 分析", "📋 事件明細", "💹 事件策略回測"])

# ===== Tab 1: CAR/AAR 分析 =====
with tab1:
    if es_result.stats.get("n_events", 0) == 0:
        st.warning("無有效事件可分析。")
    else:
        # 統計卡片
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("事件數", es_result.stats.get("n_events", 0))
        c2.metric("累積異常報酬 (CAR)", f"{es_result.stats.get('car_total', 0):.4f}")
        c3.metric("平均異常報酬 (AAR)", f"{es_result.stats.get('aar_mean', 0):.4f}")
        c4.metric("AAR > 0 比率", f"{es_result.stats.get('aar_positive_ratio', 0):.1%}")

        # CAR 折線圖
        if not es_result.car.empty:
            st.subheader("累積異常報酬 (CAR)")
            fig_car = go.Figure()
            fig_car.add_trace(go.Scatter(
                x=es_result.car["day_offset"],
                y=es_result.car["car"],
                mode="lines+markers",
                name="CAR",
                line=dict(color="#4FC3F7", width=2),
                fill="tozeroy",
                fillcolor="rgba(79,195,247,0.1)",
            ))
            fig_car.add_vline(x=0, line_dash="dash", line_color="yellow",
                              annotation_text="事件日")
            fig_car.update_layout(
                template="plotly_dark", height=400,
                xaxis_title="相對事件日（天）",
                yaxis_title="CAR",
            )
            st.plotly_chart(fig_car, use_container_width=True)

        # AAR 柱狀圖
        if not es_result.aar.empty:
            st.subheader("平均異常報酬 (AAR)")
            colors = ["#26A69A" if v >= 0 else "#EF5350" for v in es_result.aar["aar"]]
            fig_aar = go.Figure()
            fig_aar.add_trace(go.Bar(
                x=es_result.aar["day_offset"],
                y=es_result.aar["aar"],
                marker_color=colors,
                name="AAR",
            ))
            fig_aar.add_vline(x=0, line_dash="dash", line_color="yellow",
                              annotation_text="事件日")
            fig_aar.update_layout(
                template="plotly_dark", height=350,
                xaxis_title="相對事件日（天）",
                yaxis_title="AAR",
            )
            st.plotly_chart(fig_aar, use_container_width=True)

# ===== Tab 2: 事件明細 =====
with tab2:
    if events.empty:
        st.warning("無事件資料。")
    else:
        st.subheader(f"{params['event_type']} — 共 {len(events)} 筆事件")
        display_events = events.copy()
        display_events["event_date"] = display_events["event_date"].dt.strftime("%Y-%m-%d")
        st.dataframe(
            display_events.sort_values(["event_date", "stock_id"], ascending=[False, True])
            .reset_index(drop=True),
            use_container_width=True,
            hide_index=True,
        )

# ===== Tab 3: 事件策略回測 =====
with tab3:
    st.subheader("事件驅動策略回測")
    st.caption("選擇個股，使用事件訊號進行回測")

    event_stocks = events["stock_id"].unique().tolist()
    if not event_stocks:
        st.warning("無事件股票。")
    else:
        selected_stock = st.selectbox("選擇股票", sorted(event_stocks), key="event_bt_stock")

        entry_before = st.slider("進場提前天數", 1, 20, 5, key="event_bt_entry")
        exit_after = st.slider("出場延後天數", 1, 30, 10, key="event_bt_exit")

        if st.button("執行回測", key="event_bt_run"):
            stock_price = price_df[price_df["stock_id"] == selected_stock].copy()
            stock_events = events[events["stock_id"] == selected_stock].copy()

            if stock_price.empty or stock_events.empty:
                st.error("該股票無足夠資料。")
            else:
                signaled = event_trading_signals(
                    stock_events, stock_price, entry_before, exit_after
                )

                from analysis.strategies.event_driven import EventDrivenStrategy
                strategy = EventDrivenStrategy()
                bt = Backtester(strategy=strategy)
                result = bt.run(signaled)

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("總報酬率", f"{result.total_return:.2%}")
                c2.metric("Sharpe", f"{result.sharpe_ratio:.2f}")
                c3.metric("最大回撤", f"{result.max_drawdown:.2%}")
                c4.metric("交易次數", result.trade_count)

                if not result.equity_curve.empty:
                    fig_eq = go.Figure()
                    fig_eq.add_trace(go.Scatter(
                        x=result.equity_curve.index,
                        y=result.equity_curve.values,
                        mode="lines", name="權益曲線",
                    ))
                    fig_eq.update_layout(
                        template="plotly_dark", height=400,
                        yaxis_title="權益 (TWD)",
                    )
                    st.plotly_chart(fig_eq, use_container_width=True)
