"""
Page 9: 產業輪動 — 營收動能 + 法人流向 → 產業強弱排序
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

from analysis.utils.data_loader import (
    load_chip_institutional_all,
    load_industry_mapping,
    load_month_revenue_all,
)
from analysis.utils.sector_rotation import (
    calc_industry_flow,
    calc_industry_momentum,
    industry_composite_score,
    industry_rotation_history,
)

st.set_page_config(page_title="產業輪動", page_icon="🔄", layout="wide")
st.title("🔄 產業輪動分析")

# --- Sidebar ---
st.sidebar.header("分析設定")

lookback_months = st.sidebar.slider("營收回溯月數", 1, 12, 3)
lookback_days = st.sidebar.slider("法人流向回溯天數", 5, 60, 20)

m_weight = st.sidebar.slider("營收動能權重", 0.0, 1.0, 0.5, 0.1)
f_weight = 1.0 - m_weight
st.sidebar.caption(f"法人流向權重: {f_weight:.1f}")

rotation_periods = st.sidebar.slider("輪動歷史月數", 3, 24, 12)

run_btn = st.sidebar.button("執行分析", type="primary", use_container_width=True)

# --- Main ---
if run_btn:
    with st.spinner("載入資料中..."):
        industry_map = load_industry_mapping()
        if industry_map.empty:
            st.error("無產業分類資料，請先執行 `python main.py --scanner industry`")
            st.stop()

        start_date = (date.today() - timedelta(days=lookback_months * 31 + 30)).isoformat()
        revenue_df = load_month_revenue_all(start_date)
        chip_df = load_chip_institutional_all(
            (date.today() - timedelta(days=lookback_days + 5)).isoformat()
        )

    st.session_state["sr_industry_map"] = industry_map
    st.session_state["sr_revenue_df"] = revenue_df
    st.session_state["sr_chip_df"] = chip_df
    st.session_state["sr_params"] = {
        "lookback_months": lookback_months,
        "lookback_days": lookback_days,
        "m_weight": m_weight,
        "f_weight": f_weight,
        "rotation_periods": rotation_periods,
    }

if "sr_industry_map" not in st.session_state:
    st.info("請在左側面板設定參數後，點擊「執行分析」。")
    st.stop()

industry_map = st.session_state["sr_industry_map"]
revenue_df = st.session_state["sr_revenue_df"]
chip_df = st.session_state["sr_chip_df"]
params = st.session_state["sr_params"]

tab1, tab2, tab3 = st.tabs(["📊 產業排名", "🗺️ 輪動熱力圖", "📋 產業成分股"])

# ===== Tab 1: 產業排名 =====
with tab1:
    momentum = calc_industry_momentum(revenue_df, industry_map, params["lookback_months"])
    flow = calc_industry_flow(chip_df, industry_map, params["lookback_days"])
    composite = industry_composite_score(momentum, flow, params["m_weight"], params["f_weight"])

    if composite.empty:
        st.warning("無足夠資料計算產業排名。")
    else:
        st.subheader("產業綜合排名")

        # 水平 bar chart
        fig_bar = px.bar(
            composite.sort_values("final_rank", ascending=False),
            x="composite_score", y="industry",
            orientation="h",
            color="composite_score",
            color_continuous_scale="RdYlGn",
            labels={"composite_score": "綜合得分", "industry": "產業"},
        )
        fig_bar.update_layout(height=max(400, len(composite) * 25), template="plotly_dark")
        st.plotly_chart(fig_bar, use_container_width=True)

        # 排名表格
        display = composite.copy()
        display["composite_score"] = display["composite_score"].map(lambda x: f"{x:.3f}")
        st.dataframe(display.reset_index(drop=True), use_container_width=True, hide_index=True)

    # 營收動能 & 法人流向明細
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("營收動能排名")
        if not momentum.empty:
            m_display = momentum.copy()
            m_display["avg_yoy"] = m_display["avg_yoy"].map(lambda x: f"{x:.1f}%")
            m_display["positive_ratio"] = m_display["positive_ratio"].map(lambda x: f"{x:.0%}")
            st.dataframe(m_display.reset_index(drop=True), use_container_width=True, hide_index=True)
        else:
            st.warning("無營收動能資料。")

    with col2:
        st.subheader("法人流向排名")
        if not flow.empty:
            f_display = flow.copy()
            f_display["total_net_buy"] = f_display["total_net_buy"].map(lambda x: f"{x:,.0f}")
            st.dataframe(f_display.reset_index(drop=True), use_container_width=True, hide_index=True)
        else:
            st.warning("無法人流向資料。")

# ===== Tab 2: 輪動熱力圖 =====
with tab2:
    rotation = industry_rotation_history(
        revenue_df, chip_df, industry_map, params["rotation_periods"]
    )
    if rotation.empty:
        st.warning("無足夠資料產生輪動歷史。")
    else:
        st.subheader("產業輪動熱力圖（月份 × 產業，數字 = 排名）")
        fig_heatmap = px.imshow(
            rotation.values,
            x=rotation.columns.tolist(),
            y=rotation.index.tolist(),
            text_auto=True,
            color_continuous_scale="RdYlGn_r",
            labels={"x": "產業", "y": "月份", "color": "排名"},
        )
        fig_heatmap.update_layout(
            height=max(400, len(rotation) * 30),
            template="plotly_dark",
        )
        st.plotly_chart(fig_heatmap, use_container_width=True)

# ===== Tab 3: 產業成分股明細 =====
with tab3:
    industries = industry_map["industry_category"].unique().tolist()
    industries.sort()
    selected_industry = st.selectbox("選擇產業", industries)

    stocks_in_industry = industry_map[
        industry_map["industry_category"] == selected_industry
    ]["stock_id"].tolist()

    st.subheader(f"{selected_industry} — 共 {len(stocks_in_industry)} 支")

    if not revenue_df.empty:
        latest_rev = revenue_df.sort_values("date").groupby("stock_id").last().reset_index()
        in_industry = latest_rev[latest_rev["stock_id"].isin(stocks_in_industry)]
        if not in_industry.empty:
            display_cols = ["stock_id", "date"]
            if "revenue" in in_industry.columns:
                display_cols.append("revenue")
            if "month_revenue_year_on_year" in in_industry.columns:
                display_cols.append("month_revenue_year_on_year")
            st.dataframe(
                in_industry[display_cols].sort_values("stock_id").reset_index(drop=True),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("該產業無營收資料。")
    else:
        st.dataframe(
            pd.DataFrame({"stock_id": stocks_in_industry}),
            use_container_width=True,
            hide_index=True,
        )
