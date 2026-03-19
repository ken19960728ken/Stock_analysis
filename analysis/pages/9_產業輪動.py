"""
Page 9: 產業輪動 — 營收動能 + 法人流向 → 產業強弱排序
支援大類 (sector) / 次產業 (sub_industry) 兩層分析
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
    load_stock_per_all,
)
from analysis.utils.sector_rotation import (
    calc_industry_flow,
    calc_industry_momentum,
    calc_industry_valuation,
    industry_composite_score,
    industry_rotation_history,
)
from analysis.utils.supply_chain import (
    SUPPLY_CHAIN,
    calc_chain_lead_lag,
    calc_chain_momentum,
    get_chain_names,
)
from analysis.utils.granger_chain import (
    load_or_compute,
    plot_causal_network,
    discover_chains,
)

st.set_page_config(page_title="產業輪動", page_icon="🔄", layout="wide")
st.title("🔄 產業輪動分析")

# --- Sidebar ---
st.sidebar.header("分析設定")

# 分析層級
has_sub = False
analysis_level = st.sidebar.radio("分析層級", ["大類 (sector)", "次產業 (sub_industry)"])
level = "sub_industry" if "次產業" in analysis_level else "sector"

lookback_months = st.sidebar.slider("營收回溯月數", 1, 12, 3)
lookback_days = st.sidebar.slider("法人流向回溯天數", 5, 60, 20)

m_weight = st.sidebar.slider("營收動能權重", 0.0, 1.0, 0.5, 0.1)
f_weight = 1.0 - m_weight
st.sidebar.caption(f"法人流向權重: {f_weight:.1f}")

# ICIR 動態權重
st.sidebar.markdown("---")
enable_icir = st.sidebar.checkbox("啟用 ICIR 動態權重", value=False,
                                   help="根據歷史 IC 自動調整營收/法人權重，覆蓋上方手動設定")

# 估值維度
enable_valuation = st.sidebar.checkbox("加入估值維度", value=False,
                                        help="加入 PER/PBR 估值評分，避免追高估值極端的產業")
v_weight = 0.0
valuation_method = "percentile"
if enable_valuation:
    v_weight = st.sidebar.slider("估值權重", 0.0, 0.5, 0.2, 0.05,
                                  help="估值在綜合得分中的權重")
    valuation_method = st.sidebar.radio(
        "估值計分方式", ["percentile", "zscore"],
        format_func=lambda x: "百分位排名" if x == "percentile" else "Z-Score 標準化",
        help="百分位：簡單排名。Z-Score：保留分佈距離資訊（參考 SPDR Scorecard）"
    )
    # 自動按比例縮減營收/法人權重
    remaining = 1.0 - v_weight
    if (m_weight + f_weight) > 0:
        ratio = m_weight / (m_weight + f_weight)
        m_weight = remaining * ratio
        f_weight = remaining - m_weight
    else:
        m_weight = remaining / 2
        f_weight = remaining / 2
    st.sidebar.caption(f"調整後：營收 {m_weight:.0%} / 法人 {f_weight:.0%} / 估值 {v_weight:.0%}")

# 衰減加權設定
enable_decay = st.sidebar.checkbox("啟用衰減加權", value=False,
                                    help="啟用後近期資料權重更高，遠期資料權重指數衰減")
momentum_decay_hl: int | None = None
flow_decay_hl: int | None = None
if enable_decay:
    momentum_decay_hl = st.sidebar.slider("營收衰減半衰期（月）", 1, 6, 2,
                                           help="半衰期越短，近期營收的影響力越大")
    flow_decay_hl = st.sidebar.slider("法人衰減半衰期（天）", 3, 30, 7,
                                       help="半衰期越短，近期法人動向影響力越大")

rotation_periods = st.sidebar.slider("輪動歷史月數", 3, 24, 12)

run_btn = st.sidebar.button("執行分析", type="primary", use_container_width=True)

# --- Main ---
if run_btn:
    with st.spinner("載入資料中..."):
        industry_map = load_industry_mapping()
        if industry_map.empty:
            st.error("無產業分類資料，請先執行 `python main.py --scanner industry`")
            st.stop()

        # 檢查是否有次產業資料
        has_sub = "sub_industry" in industry_map.columns and industry_map["sub_industry"].notna().any()

        start_date = (date.today() - timedelta(days=lookback_months * 31 + 30)).isoformat()
        revenue_df = load_month_revenue_all(start_date)
        chip_df = load_chip_institutional_all(
            (date.today() - timedelta(days=lookback_days + 5)).isoformat()
        )

    # 估值維度資料
    if enable_valuation:
        per_df = load_stock_per_all(start_date)
        st.session_state["sr_per_df"] = per_df
    else:
        st.session_state.pop("sr_per_df", None)

    st.session_state["sr_industry_map"] = industry_map
    st.session_state["sr_revenue_df"] = revenue_df
    st.session_state["sr_chip_df"] = chip_df
    st.session_state["sr_has_sub"] = has_sub
    st.session_state["sr_params"] = {
        "lookback_months": lookback_months,
        "lookback_days": lookback_days,
        "m_weight": m_weight,
        "f_weight": f_weight,
        "v_weight": v_weight,
        "rotation_periods": rotation_periods,
        "level": level,
        "momentum_decay_hl": momentum_decay_hl,
        "flow_decay_hl": flow_decay_hl,
        "enable_icir": enable_icir,
        "enable_valuation": enable_valuation,
        "valuation_method": valuation_method,
    }

if "sr_industry_map" not in st.session_state:
    st.info("請在左側面板設定參數後，點擊「執行分析」。")
    st.stop()

industry_map = st.session_state["sr_industry_map"]
revenue_df = st.session_state["sr_revenue_df"]
chip_df = st.session_state["sr_chip_df"]
has_sub = st.session_state.get("sr_has_sub", False)
params = st.session_state["sr_params"]

if level == "sub_industry" and not has_sub:
    st.warning("目前無次產業分類資料，將自動使用大類分析。")
    level = "sector"

tab1, tab2, tab3, tab4 = st.tabs(["📊 產業排名", "🗺️ 輪動熱力圖", "📋 產業成分股", "🔗 供應鏈分析"])

# ===== Tab 1: 產業排名 =====
with tab1:
    momentum = calc_industry_momentum(revenue_df, industry_map,
                                       params["lookback_months"], level=level,
                                       decay_half_life=params.get("momentum_decay_hl"))
    flow = calc_industry_flow(chip_df, industry_map,
                              params["lookback_days"], level=level,
                              decay_half_life=params.get("flow_decay_hl"))

    # ICIR 動態權重：根據因子得分的離散度估算有效性
    dynamic_weights = None
    if params.get("enable_icir"):
        # 因子得分的離散度越大 → 區分力越強 → 權重越高
        m_spread = momentum["momentum_score"].std() if not momentum.empty and "momentum_score" in momentum.columns else 0.0
        f_spread = flow["flow_score"].std() if not flow.empty and "flow_score" in flow.columns else 0.0

        # 估值維度的離散度（預先計算供 ICIR 使用）
        v_spread = 0.0
        if params.get("enable_valuation") and "sr_per_df" in st.session_state:
            pre_valuation = calc_industry_valuation(
                st.session_state["sr_per_df"], industry_map, level=level,
                method=params.get("valuation_method", "percentile"),
            )
            if not pre_valuation.empty and "valuation_score" in pre_valuation.columns:
                v_spread = pre_valuation["valuation_score"].std()

        total_spread = m_spread + f_spread + v_spread
        if total_spread > 0:
            dw_m = round(m_spread / total_spread, 2)
            dw_f = round(f_spread / total_spread, 2)
            dw_v = round(v_spread / total_spread, 2)
            dynamic_weights = {"momentum": dw_m, "flow": dw_f}
            if dw_v > 0:
                dynamic_weights["valuation"] = dw_v

    # 估值維度
    valuation = None
    if params.get("enable_valuation") and "sr_per_df" in st.session_state:
        valuation = calc_industry_valuation(
            st.session_state["sr_per_df"], industry_map, level=level,
            method=params.get("valuation_method", "percentile"),
        )

    composite = industry_composite_score(
        momentum, flow, params["m_weight"], params["f_weight"],
        dynamic_weights=dynamic_weights,
        valuation=valuation, v_weight=params.get("v_weight", 0.0),
    )

    if composite.empty:
        st.warning("無足夠資料計算產業排名。")
    else:
        level_label = "次產業" if level == "sub_industry" else "大類"
        st.subheader(f"產業綜合排名（{level_label}）")

        # 顯示當前使用的模型設定
        setting_parts = []
        if dynamic_weights:
            dw_label = f"ICIR 動態權重：營收 {dynamic_weights['momentum']:.0%} / 法人 {dynamic_weights['flow']:.0%}"
            if "valuation" in dynamic_weights:
                dw_label += f" / 估值 {dynamic_weights['valuation']:.0%}"
            setting_parts.append(dw_label)
        else:
            w_label = f"靜態權重：營收 {params['m_weight']:.0%} / 法人 {params['f_weight']:.0%}"
            if params.get("v_weight", 0) > 0:
                w_label += f" / 估值 {params['v_weight']:.0%}"
            setting_parts.append(w_label)
        if params.get("enable_valuation"):
            method_label = "百分位" if params.get("valuation_method") == "percentile" else "Z-Score"
            setting_parts.append(f"估值計分：{method_label}")
        if params.get("momentum_decay_hl"):
            setting_parts.append(f"營收衰減 {params['momentum_decay_hl']}月")
        if params.get("flow_decay_hl"):
            setting_parts.append(f"法人衰減 {params['flow_decay_hl']}天")
        sep = " ｜ "
        st.caption(f"{sep.join(setting_parts)}")

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

    # 營收動能 & 法人流向 & 估值明細
    if valuation is not None and not valuation.empty:
        col1, col2, col3 = st.columns(3)
    else:
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

    if valuation is not None and not valuation.empty:
        with col3:
            st.subheader("估值排名")
            v_display = valuation.copy()
            v_display["avg_per"] = v_display["avg_per"].map(lambda x: f"{x:.1f}")
            v_display["avg_pbr"] = v_display["avg_pbr"].map(lambda x: f"{x:.2f}")
            v_display["valuation_score"] = v_display["valuation_score"].map(lambda x: f"{x:.3f}")
            st.dataframe(v_display.reset_index(drop=True), use_container_width=True, hide_index=True)

# ===== Tab 2: 輪動熱力圖 =====
with tab2:
    rotation = industry_rotation_history(
        revenue_df, chip_df, industry_map, params["rotation_periods"],
        level=level,
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
    # 根據 level 選擇分類欄位
    if level == "sub_industry" and "sub_industry" in industry_map.columns:
        # 兩層鑽取：先選大類，再選次產業
        sector_col = "sector" if "sector" in industry_map.columns else "industry_category"
        sectors = sorted(industry_map[sector_col].dropna().unique().tolist())
        selected_sector = st.selectbox("選擇大類", sectors)

        sub_df = industry_map[industry_map[sector_col] == selected_sector]
        subs = sub_df["sub_industry"].dropna().unique().tolist()
        if subs:
            subs.sort()
            selected_sub = st.selectbox("選擇次產業", ["全部"] + subs)
            if selected_sub == "全部":
                stocks_in_industry = sub_df["stock_id"].tolist()
                display_title = f"{selected_sector}（全部）"
            else:
                stocks_in_industry = sub_df[sub_df["sub_industry"] == selected_sub]["stock_id"].tolist()
                display_title = f"{selected_sector} / {selected_sub}"
        else:
            stocks_in_industry = sub_df["stock_id"].tolist()
            display_title = selected_sector
    else:
        group_col = "industry_category" if "industry_category" in industry_map.columns else "sector"
        industries = sorted(industry_map[group_col].dropna().unique().tolist())
        selected_industry = st.selectbox("選擇產業", industries)
        stocks_in_industry = industry_map[
            industry_map[group_col] == selected_industry
        ]["stock_id"].tolist()
        display_title = selected_industry

    st.subheader(f"{display_title} — 共 {len(stocks_in_industry)} 支")

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

# ===== Tab 4: 供應鏈分析 =====
with tab4:
    chain_mode = st.radio(
        "分析模式", ["手動定義", "自動發現（Granger 因果）"],
        horizontal=True,
    )

    if chain_mode == "手動定義":
        # === 原有手動供應鏈邏輯（完全不動）===
        chain_names = get_chain_names()
        selected_chain = st.selectbox("選擇供應鏈", chain_names)

        if selected_chain:
            stages = SUPPLY_CHAIN[selected_chain]
            arrow_sep = " → "
            st.caption(f"供應鏈順序（上游→下游）：{arrow_sep.join(stages)}")

            # 供應鏈營收動能
            chain_mom = calc_chain_momentum(
                selected_chain, revenue_df, industry_map,
                lookback_months=params["lookback_months"],
            )

            if not chain_mom.empty:
                st.subheader("各環節營收動能")

                fig_chain = px.bar(
                    chain_mom,
                    y="sub_industry",
                    x="avg_yoy",
                    orientation="h",
                    color="avg_yoy",
                    color_continuous_scale=[[0, "#EF5350"], [0.5, "#757575"], [1, "#26A69A"]],
                    labels={"avg_yoy": "平均營收 YoY%", "sub_industry": "環節"},
                    text="avg_yoy",
                )
                fig_chain.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
                fig_chain.update_layout(
                    height=max(300, len(chain_mom) * 50),
                    template="plotly_dark",
                    yaxis=dict(categoryorder="array", categoryarray=list(reversed(stages))),
                )
                st.plotly_chart(fig_chain, use_container_width=True)

                display_mom = chain_mom[["sub_industry", "avg_yoy", "median_yoy", "stock_count"]].copy()
                display_mom.columns = ["環節", "平均YoY%", "中位YoY%", "家數"]
                display_mom["平均YoY%"] = display_mom["平均YoY%"].map(lambda x: f"{x:.1f}%")
                display_mom["中位YoY%"] = display_mom["中位YoY%"].map(lambda x: f"{x:.1f}%")
                st.dataframe(display_mom.reset_index(drop=True), use_container_width=True, hide_index=True)
            else:
                st.info("無足夠資料計算供應鏈動能。")

            st.subheader("領先落後矩陣")
            st.caption("正值 = 行領先列 N 個月，負值 = 行落後列 N 個月")

            lead_lag = calc_chain_lead_lag(
                selected_chain, revenue_df, industry_map,
                periods=params["rotation_periods"],
            )

            if not lead_lag.empty:
                fig_ll = px.imshow(
                    lead_lag.values.astype(float),
                    x=lead_lag.columns.tolist(),
                    y=lead_lag.index.tolist(),
                    text_auto=True,
                    color_continuous_scale="RdBu",
                    labels={"color": "領先月數"},
                )
                fig_ll.update_layout(
                    height=max(350, len(lead_lag) * 50),
                    template="plotly_dark",
                )
                st.plotly_chart(fig_ll, use_container_width=True)
            else:
                st.info("無足夠資料計算領先落後關係。")

    else:
        # === 自動發現（Granger 因果）===
        st.caption("使用 Granger 因果檢定自動偵測次產業間的營收連動關係")

        gc_col1, gc_col2 = st.columns(2)
        with gc_col1:
            gc_max_lag = st.slider("最大滯後期數", 1, 6, 3,
                                    help="Granger 檢定的最大 lag（月）")
        with gc_col2:
            gc_p_threshold = st.select_slider(
                "顯著性門檻", options=[0.01, 0.05, 0.10], value=0.05,
                help="p-value 門檻，越小越嚴格"
            )

        gc_run = st.button("執行 Granger 檢定", type="primary")

        if gc_run:
            with st.spinner("計算 Granger 因果檢定中（約 5-15 秒）..."):
                pairs, graph = load_or_compute(
                    revenue_df, industry_map,
                    max_lag=gc_max_lag, p_threshold=gc_p_threshold,
                )
            st.session_state["gc_pairs"] = pairs
            st.session_state["gc_graph"] = graph

        if "gc_pairs" in st.session_state:
            pairs = st.session_state["gc_pairs"]
            graph = st.session_state["gc_graph"]

            if pairs.empty:
                st.info("在目前的參數下，無顯著的 Granger 因果關係。")
            else:
                node_count = len(graph.nodes)
                edge_count = len(graph.edges)
                st.subheader(f"因果網絡圖（{node_count} 個節點，{edge_count} 條邊）")
                fig_network = plot_causal_network(graph, industry_map)
                st.plotly_chart(fig_network, use_container_width=True)

                st.subheader("顯著因果關係")
                display_pairs = pairs.copy()
                display_pairs["p_value"] = display_pairs["p_value"].map(lambda x: f"{x:.4f}")
                display_pairs["f_stat"] = display_pairs["f_stat"].map(lambda x: f"{x:.2f}")
                display_pairs.columns = ["來源（領先）", "目標（落後）", "滯後月數", "F-stat", "p-value"]
                st.dataframe(display_pairs.reset_index(drop=True),
                             use_container_width=True, hide_index=True)

                chains = discover_chains(graph)
                if chains:
                    st.subheader("自動發現的供應鏈")
                    for i, chain in enumerate(chains[:10], 1):
                        chain_arrow = " → ".join(chain)
                        chain_len = len(chain)
                        st.write(f"**鏈 {i}**（{chain_len} 環節）：{chain_arrow}")
                else:
                    st.info("未發現長度 ≥ 3 的供應鏈路徑。")
