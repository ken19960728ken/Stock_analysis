"""
Page 2: 因子篩選 — 多維度條件過濾，選股工具
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = str(Path(__file__).resolve().parents[2])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from analysis.utils.data_loader import (
    get_stock_list,
    load_latest_institutional_all,
    load_latest_per_all,
    load_latest_price_all,
    load_latest_revenue_all,
)

st.set_page_config(page_title="因子篩選", page_icon="🔍", layout="wide")
st.title("🔍 因子篩選")

# --- 載入資料 ---
with st.spinner("載入資料中..."):
    stocks = get_stock_list()
    prices = load_latest_price_all()
    per_data = load_latest_per_all()
    revenue_data = load_latest_revenue_all()
    inst_data = load_latest_institutional_all()

if stocks.empty:
    st.warning("無法載入股票清單")
    st.stop()

# 合併資料
merged = stocks.copy()
merged["stock_id"] = merged["stock_id"].astype(str).str.strip()

if not prices.empty:
    prices["stock_id"] = prices["stock_id"].astype(str).str.strip()
    merged = merged.merge(
        prices[["stock_id", "close", "volume"]].rename(columns={"close": "收盤價", "volume": "成交量"}),
        on="stock_id", how="left",
    )

if not per_data.empty:
    per_data["stock_id"] = per_data["stock_id"].astype(str).str.strip()
    # 實際欄位: per, pbr, dividend_yield
    rename_map = {}
    if "per" in per_data.columns:
        rename_map["per"] = "P/E"
    if "pbr" in per_data.columns:
        rename_map["pbr"] = "P/B"
    if "dividend_yield" in per_data.columns:
        rename_map["dividend_yield"] = "殖利率"
    if rename_map:
        select_cols = ["stock_id"] + list(rename_map.keys())
        per_subset = per_data[select_cols].rename(columns=rename_map)
        merged = merged.merge(per_subset, on="stock_id", how="left")

if not revenue_data.empty:
    revenue_data["stock_id"] = revenue_data["stock_id"].astype(str).str.strip()
    rev_col = None
    for c in revenue_data.columns:
        if "revenue" in c.lower() or "營收" in c:
            rev_col = c
            break
    if rev_col:
        merged = merged.merge(
            revenue_data[["stock_id", rev_col]].rename(columns={rev_col: "月營收"}),
            on="stock_id", how="left",
        )

if not inst_data.empty:
    inst_data["stock_id"] = inst_data["stock_id"].astype(str).str.strip()
    buy_col = None
    for c in inst_data.columns:
        if "buy" in c.lower() or "買" in c or "Foreign" in c:
            buy_col = c
            break
    if buy_col:
        merged = merged.merge(
            inst_data[["stock_id", buy_col]].rename(columns={buy_col: "法人買賣超"}),
            on="stock_id", how="left",
        )

# --- Sidebar 篩選面板 ---
st.sidebar.header("篩選條件")

# 估值面
st.sidebar.subheader("估值面")
if "P/E" in merged.columns:
    pe_range = st.sidebar.slider("P/E 範圍", 0.0, 100.0, (5.0, 30.0), step=0.5)
else:
    pe_range = None

if "P/B" in merged.columns:
    pb_range = st.sidebar.slider("P/B 範圍", 0.0, 20.0, (0.0, 5.0), step=0.1)
else:
    pb_range = None

if "殖利率" in merged.columns:
    dy_min = st.sidebar.slider("殖利率 >=", 0.0, 15.0, 0.0, step=0.5)
else:
    dy_min = None

# 技術面
st.sidebar.subheader("技術面")
if "收盤價" in merged.columns:
    price_range = st.sidebar.slider("股價範圍", 0, 5000, (10, 2000), step=10)
else:
    price_range = None

if "成交量" in merged.columns:
    vol_min = st.sidebar.number_input("最低成交量", value=0, step=100)
else:
    vol_min = None

# 類型篩選
stock_types = ["全部"] + sorted(merged["type"].dropna().unique().tolist())
selected_type = st.sidebar.selectbox("商品類型", stock_types)

# --- 套用篩選 ---
filtered = merged.copy()

if selected_type != "全部":
    filtered = filtered[filtered["type"] == selected_type]

if pe_range and "P/E" in filtered.columns:
    pe_vals = pd.to_numeric(filtered["P/E"], errors="coerce")
    filtered = filtered[((pe_vals >= pe_range[0]) & (pe_vals <= pe_range[1])) | pe_vals.isna()]

if pb_range and "P/B" in filtered.columns:
    pb_vals = pd.to_numeric(filtered["P/B"], errors="coerce")
    filtered = filtered[((pb_vals >= pb_range[0]) & (pb_vals <= pb_range[1])) | pb_vals.isna()]

if dy_min and "殖利率" in filtered.columns:
    dy_vals = pd.to_numeric(filtered["殖利率"], errors="coerce")
    filtered = filtered[(dy_vals >= dy_min) | dy_vals.isna()]

if price_range and "收盤價" in filtered.columns:
    p_vals = pd.to_numeric(filtered["收盤價"], errors="coerce")
    filtered = filtered[((p_vals >= price_range[0]) & (p_vals <= price_range[1])) | p_vals.isna()]

if vol_min and "成交量" in filtered.columns:
    v_vals = pd.to_numeric(filtered["成交量"], errors="coerce")
    filtered = filtered[(v_vals >= vol_min) | v_vals.isna()]

# 移除全部都是 NaN 的篩選結果
has_data = False
for c in ["收盤價", "P/E", "P/B", "殖利率"]:
    if c in filtered.columns and filtered[c].notna().any():
        has_data = True
        break

# --- 顯示結果 ---
st.subheader(f"篩選結果: {len(filtered)} 檔 / {len(merged)} 檔")

# 排序選項
sort_col = st.selectbox(
    "排序依據",
    [c for c in filtered.columns if c not in ("market",)],
    index=0,
)
sort_asc = st.checkbox("升冪排序", value=True)
filtered_sorted = filtered.sort_values(sort_col, ascending=sort_asc, na_position="last")

# 顯示表格
display_cols = ["stock_id", "name", "type"]
for c in ["收盤價", "成交量", "P/E", "P/B", "殖利率", "月營收", "法人買賣超"]:
    if c in filtered_sorted.columns:
        display_cols.append(c)

st.dataframe(
    filtered_sorted[display_cols].reset_index(drop=True),
    use_container_width=True,
    height=600,
)

# CSV 匯出
csv = filtered_sorted[display_cols].to_csv(index=False)
st.download_button(
    label="📥 匯出 CSV",
    data=csv,
    file_name="factor_screening.csv",
    mime="text/csv",
)
