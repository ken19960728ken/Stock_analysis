"""
Page 6: 市場總覽 — 全市場概覽、資金流向、類股表現
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = str(Path(__file__).resolve().parents[2])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from analysis.utils.data_loader import (
    FRED_CATEGORIES,
    FRED_INDICATORS,
    get_stock_list,
    is_fred_available,
    load_fred_series,
    load_industry_mapping,
    load_latest_institutional_all,
    load_latest_per_all,
    load_latest_price_all,
    load_market_summary,
)
from analysis.utils.charts import (
    create_economic_indicator_chart,
    create_industry_treemap,
    create_yield_spread_chart,
)
from core.db import safe_read_sql

st.set_page_config(page_title="市場總覽", page_icon="🌐", layout="wide")
st.title("🌐 市場總覽")

# --- 載入資料 ---
with st.spinner("載入市場資料..."):
    stocks = get_stock_list()
    prices = load_latest_price_all()
    per_data = load_latest_per_all()
    inst_data = load_latest_institutional_all()
    market_stats = load_market_summary()

# --- 市場指標卡片 ---
st.header("市場快照")
cols = st.columns(4)

up_count = market_stats.get("up_count", 0)
down_count = market_stats.get("down_count", 0)
total = market_stats.get("total", 0)

cols[0].metric("上漲家數", f"{up_count}", f"/ {total} 檔")
cols[1].metric("下跌家數", f"{down_count}", f"/ {total} 檔")

# 法人淨買超
if not inst_data.empty:
    buy_col = None
    for c in inst_data.columns:
        if "buy" in c.lower() or "買" in c or "Foreign" in c:
            buy_col = c
            break
    if buy_col:
        total_inst = pd.to_numeric(inst_data[buy_col], errors="coerce").sum()
        cols[2].metric("法人淨買超(今日)", f"{total_inst:,.0f}")
    else:
        cols[2].metric("法人淨買超", "N/A")
else:
    cols[2].metric("法人淨買超", "N/A")

# 市場平均 P/E
if not per_data.empty:
    pe_col = None
    for c in per_data.columns:
        if c == "per" or "PER" in c:
            pe_col = c
            break
    if pe_col:
        pe_vals = pd.to_numeric(per_data[pe_col], errors="coerce")
        avg_pe = pe_vals[(pe_vals > 0) & (pe_vals < 200)].mean()
        cols[3].metric("市場平均 P/E", f"{avg_pe:.1f}" if not np.isnan(avg_pe) else "N/A")
    else:
        cols[3].metric("市場平均 P/E", "N/A")
else:
    cols[3].metric("市場平均 P/E", "N/A")

# --- 漲跌幅分佈 ---
st.header("漲跌分佈")
if not prices.empty:
    merged = stocks.merge(
        prices.rename(columns={"close": "close_price"}),
        on="stock_id", how="inner",
    )

    # 嘗試取得漲跌幅
    try:
        sql = """
        WITH ranked AS (
            SELECT stock_id, close, date,
                   ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) as rn
            FROM daily_price
        )
        SELECT a.stock_id,
               a.close AS today_close,
               b.close AS prev_close,
               (a.close - b.close) / NULLIF(b.close, 0) * 100 AS change_pct
        FROM ranked a
        JOIN ranked b ON a.stock_id = b.stock_id AND b.rn = 2
        WHERE a.rn = 1
        """
        change_df = safe_read_sql(sql)

        if not change_df.empty:
            fig_dist = go.Figure()
            fig_dist.add_trace(go.Histogram(
                x=change_df["change_pct"].clip(-10, 10),
                nbinsx=80,
                marker_color="#4FC3F7",
                name="漲跌幅",
            ))
            fig_dist.add_vline(x=0, line_dash="dash", line_color="white")
            fig_dist.update_layout(
                title="全市場漲跌幅分佈",
                xaxis_title="漲跌幅 (%)",
                yaxis_title="家數",
                template="plotly_dark",
                height=350,
            )
            st.plotly_chart(fig_dist, use_container_width=True)
    except Exception:
        st.info("無法計算漲跌幅分佈")

# --- 法人動態排行 ---
st.header("法人動態排行")
if not inst_data.empty and buy_col:
    inst_merged = inst_data.merge(
        stocks[["stock_id", "name"]], on="stock_id", how="left"
    )
    inst_merged["display"] = inst_merged["stock_id"].fillna("") + " " + inst_merged["name"].fillna("")
    inst_merged[buy_col] = pd.to_numeric(inst_merged[buy_col], errors="coerce")
    inst_sorted = inst_merged.sort_values(buy_col, ascending=False).dropna(subset=[buy_col])

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Top 20 買超")
        top_buy = inst_sorted.head(20)[["display", buy_col]].reset_index(drop=True)
        top_buy.columns = ["標的", "買超(張)"]
        st.dataframe(top_buy, use_container_width=True)

    with col_b:
        st.subheader("Top 20 賣超")
        top_sell = inst_sorted.tail(20).sort_values(buy_col)[["display", buy_col]].reset_index(drop=True)
        top_sell.columns = ["標的", "賣超(張)"]
        st.dataframe(top_sell, use_container_width=True)
else:
    st.info("無法人資料")

# --- 產業熱力圖 ---
st.header("產業熱力圖")
try:
    industry_map = load_industry_mapping()
    if not industry_map.empty and not prices.empty:
        # 計算漲跌幅
        change_sql = """
        WITH ranked AS (
            SELECT stock_id, close, volume, date,
                   ROW_NUMBER() OVER (PARTITION BY stock_id ORDER BY date DESC) as rn
            FROM daily_price
        )
        SELECT a.stock_id,
               a.close,
               a.volume,
               (a.close - b.close) / NULLIF(b.close, 0) * 100 AS change_pct
        FROM ranked a
        JOIN ranked b ON a.stock_id = b.stock_id AND b.rn = 2
        WHERE a.rn = 1
        """
        price_change = safe_read_sql(change_sql)

        if not price_change.empty:
            # TreeMap（全寬）
            fig_treemap = create_industry_treemap(
                price_change, industry_map,
                value_col="volume", color_col="change_pct",
                title="次產業漲跌熱力圖（面積=成交量，顏色=漲跌幅）",
            )
            st.plotly_chart(fig_treemap, use_container_width=True)

            # 產業漲跌排行（雙欄）
            merged_ind = price_change.merge(
                industry_map[["stock_id", "sector", "sub_industry"]],
                on="stock_id", how="inner",
            )
            merged_ind["sub_industry"] = merged_ind["sub_industry"].fillna(merged_ind["sector"])
            merged_ind["change_pct"] = pd.to_numeric(merged_ind["change_pct"], errors="coerce")
            merged_ind["volume"] = pd.to_numeric(merged_ind["volume"], errors="coerce")

            sub_agg = merged_ind.groupby("sub_industry").agg(
                avg_change=("change_pct", "mean"),
                total_volume=("volume", "sum"),
                stock_count=("stock_id", "count"),
            ).reset_index().sort_values("avg_change", ascending=False)

            col_strong, col_weak = st.columns(2)
            with col_strong:
                st.subheader("Top 10 強勢次產業")
                top10 = sub_agg.head(10).copy()
                top10["avg_change"] = top10["avg_change"].map(lambda x: f"{x:+.2f}%")
                top10["total_volume"] = top10["total_volume"].map(lambda x: f"{x:,.0f}")
                top10.columns = ["次產業", "平均漲跌幅", "總成交量", "家數"]
                st.dataframe(top10.reset_index(drop=True), use_container_width=True, hide_index=True)

            with col_weak:
                st.subheader("Top 10 弱勢次產業")
                bot10 = sub_agg.tail(10).sort_values("avg_change").copy()
                bot10["avg_change"] = bot10["avg_change"].map(lambda x: f"{x:+.2f}%")
                bot10["total_volume"] = bot10["total_volume"].map(lambda x: f"{x:,.0f}")
                bot10.columns = ["次產業", "平均漲跌幅", "總成交量", "家數"]
                st.dataframe(bot10.reset_index(drop=True), use_container_width=True, hide_index=True)
    else:
        st.info("無產業分類資料")
except Exception as e:
    st.info(f"產業熱力圖載入失敗: {e}")

# --- 估值分佈 ---
st.header("估值分佈")
if not per_data.empty and pe_col:
    col_a, col_b = st.columns(2)

    with col_a:
        pe_vals = pd.to_numeric(per_data[pe_col], errors="coerce")
        valid_pe = pe_vals[(pe_vals > 0) & (pe_vals < 200)]
        if not valid_pe.empty:
            fig_pe = go.Figure()
            fig_pe.add_trace(go.Histogram(
                x=valid_pe, nbinsx=60,
                marker_color="#BA68C8", name="P/E",
            ))
            mean_pe = valid_pe.mean()
            median_pe = valid_pe.median()
            fig_pe.add_vline(x=mean_pe, line_dash="dash", line_color="yellow",
                              annotation_text=f"均值 {mean_pe:.1f}")
            fig_pe.add_vline(x=median_pe, line_dash="dot", line_color="white",
                              annotation_text=f"中位數 {median_pe:.1f}")
            fig_pe.update_layout(
                title="全市場 P/E 分佈",
                xaxis_title="P/E",
                yaxis_title="家數",
                template="plotly_dark",
                height=350,
            )
            st.plotly_chart(fig_pe, use_container_width=True)

    with col_b:
        # P/B 分佈
        pb_col = None
        for c in per_data.columns:
            if c == "pbr" or "PBR" in c:
                pb_col = c
                break
        if pb_col:
            pb_vals = pd.to_numeric(per_data[pb_col], errors="coerce")
            valid_pb = pb_vals[(pb_vals > 0) & (pb_vals < 20)]
            if not valid_pb.empty:
                fig_pb = go.Figure()
                fig_pb.add_trace(go.Histogram(
                    x=valid_pb, nbinsx=60,
                    marker_color="#26A69A", name="P/B",
                ))
                mean_pb = valid_pb.mean()
                fig_pb.add_vline(x=mean_pb, line_dash="dash", line_color="yellow",
                                  annotation_text=f"均值 {mean_pb:.1f}")
                fig_pb.update_layout(
                    title="全市場 P/B 分佈",
                    xaxis_title="P/B",
                    yaxis_title="家數",
                    template="plotly_dark",
                    height=350,
                )
                st.plotly_chart(fig_pb, use_container_width=True)
else:
    st.info("無估值資料")

# --- 殖利率排行 ---
st.header("高殖利率排行")
if not per_data.empty:
    dy_col = None
    for c in per_data.columns:
        if c == "dividend_yield" or "Dividend" in c or "Yield" in c:
            dy_col = c
            break
    if dy_col:
        dy_merged = per_data.merge(
            stocks[["stock_id", "name"]], on="stock_id", how="left"
        )
        dy_merged[dy_col] = pd.to_numeric(dy_merged[dy_col], errors="coerce")
        dy_sorted = dy_merged[dy_merged[dy_col] > 0].sort_values(
            dy_col, ascending=False
        ).head(30)

        if not dy_sorted.empty:
            display = dy_sorted[["stock_id", "name", dy_col]].reset_index(drop=True)
            display.columns = ["代號", "名稱", "殖利率(%)"]
            st.dataframe(display, use_container_width=True)

# ---------------------------------------------------------------------------
# 經濟指標（FRED API）
# ---------------------------------------------------------------------------
st.header("經濟指標")

if is_fred_available():
    from datetime import datetime
    from dateutil.relativedelta import relativedelta

    _range_map = {"1Y": 1, "3Y": 3, "5Y": 5, "10Y": 10, "MAX": None}
    selected_range = st.radio("時間範圍", list(_range_map.keys()), horizontal=True, index=1)

    _years = _range_map[selected_range]
    _end = datetime.today().strftime("%Y-%m-%d")
    _start = (datetime.today() - relativedelta(years=_years)).strftime("%Y-%m-%d") if _years else None

    # --- 美國總經 ---
    st.subheader("美國總經")
    _macro_keys = FRED_CATEGORIES["美國總經"]
    row1_a, row1_b = st.columns(2)
    with row1_a:
        df = load_fred_series(_macro_keys[0], _start, _end)
        st.plotly_chart(create_economic_indicator_chart(df, FRED_INDICATORS[_macro_keys[0]]), use_container_width=True)
    with row1_b:
        df = load_fred_series(_macro_keys[1], _start, _end)
        st.plotly_chart(create_economic_indicator_chart(df, FRED_INDICATORS[_macro_keys[1]]), use_container_width=True)

    row2_a, row2_b = st.columns(2)
    with row2_a:
        df = load_fred_series(_macro_keys[2], _start, _end)
        st.plotly_chart(create_economic_indicator_chart(df, FRED_INDICATORS[_macro_keys[2]]), use_container_width=True)
    with row2_b:
        df = load_fred_series(_macro_keys[3], _start, _end)
        st.plotly_chart(create_economic_indicator_chart(df, FRED_INDICATORS[_macro_keys[3]]), use_container_width=True)

    # --- 美國市場 ---
    st.subheader("美國市場")
    _mkt_keys = FRED_CATEGORIES["美國市場"]
    row3_a, row3_b = st.columns(2)
    with row3_a:
        df = load_fred_series(_mkt_keys[0], _start, _end)
        st.plotly_chart(create_economic_indicator_chart(df, FRED_INDICATORS[_mkt_keys[0]]), use_container_width=True)
    with row3_b:
        df = load_fred_series(_mkt_keys[1], _start, _end)
        st.plotly_chart(create_economic_indicator_chart(df, FRED_INDICATORS[_mkt_keys[1]]), use_container_width=True)

    # 殖利率 + 利差（全寬）
    df_10y = load_fred_series("treasury_10y", _start, _end)
    df_2y = load_fred_series("treasury_2y", _start, _end)
    st.plotly_chart(create_yield_spread_chart(df_10y, df_2y), use_container_width=True)

    # --- 商品與台灣 ---
    st.subheader("商品與台灣")
    _com_keys = FRED_CATEGORIES["商品與台灣"]
    row4_a, row4_b = st.columns(2)
    with row4_a:
        df = load_fred_series(_com_keys[0], _start, _end)
        st.plotly_chart(create_economic_indicator_chart(df, FRED_INDICATORS[_com_keys[0]]), use_container_width=True)
    with row4_b:
        df = load_fred_series(_com_keys[1], _start, _end)
        st.plotly_chart(create_economic_indicator_chart(df, FRED_INDICATORS[_com_keys[1]]), use_container_width=True)

    row5_a, row5_b = st.columns(2)
    with row5_a:
        df = load_fred_series(_com_keys[2], _start, _end)
        st.plotly_chart(create_economic_indicator_chart(df, FRED_INDICATORS[_com_keys[2]]), use_container_width=True)
    with row5_b:
        df = load_fred_series(_com_keys[3], _start, _end)
        st.plotly_chart(create_economic_indicator_chart(df, FRED_INDICATORS[_com_keys[3]]), use_container_width=True)

else:
    st.info(
        "未偵測到 FRED API Key，經濟指標功能已停用。\n\n"
        "**設定方式：**\n"
        "1. 前往 https://fred.stlouisfed.org/docs/api/api_key.html 申請免費 API Key\n"
        "2. 在專案根目錄的 `.env` 檔案中加入：`FRED_API_KEY=your_key_here`\n"
        "3. 重新啟動 Streamlit 即可看到經濟指標圖表"
    )

st.caption("資料來源: Supabase PostgreSQL / FRED | 更新頻率: 依 Scanner 執行時間")
