"""持倉追蹤儀表板 — 從 Top 20 挑選買入後的持倉狀態與出場訊號

⚠️ 開發模式：預設讀本地 SQLite；正式環境設 RECOMMENDATION_DB_SOURCE=supabase。

區塊：
  1. 概覽（持有中檔數、平均未實現損益、已平倉勝率）
  2. 持有中部位（未實現損益、持有交易日、峰值）
  3. 已平倉部位（出場原因分佈 + 已實現損益）
"""

import os
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.utils.recommendation_db import load_tracked_positions

st.set_page_config(page_title="持倉追蹤", page_icon="📌", layout="wide")
st.title("持倉追蹤與出場訊號")

data_source = os.getenv("RECOMMENDATION_DB_SOURCE", "sqlite")
if data_source == "sqlite":
    st.caption("⚠️ 開發模式 — 使用本地 SQLite 資料。正式環境請設 `RECOMMENDATION_DB_SOURCE=supabase`。")

df = load_tracked_positions()
if df.empty:
    st.warning("尚無持倉記錄。請先執行 `uv run python main.py --track-positions`（需有當日選股推薦）。")
    st.stop()

df["report_date"] = pd.to_datetime(df["report_date"])
open_df = df[df["status"] == "open"].copy()
closed_df = df[df["status"] == "closed"].copy()

# ===================================================================
# 1. 概覽
# ===================================================================
c1, c2, c3, c4 = st.columns(4)
c1.metric("持有中", f"{len(open_df)} 檔")
avg_unreal = open_df["unrealized_pnl_pct"].mean() if not open_df.empty else 0.0
c2.metric("平均未實現損益", f"{avg_unreal:+.2f}%")
if not closed_df.empty:
    win_rate = (closed_df["realized_pnl_pct"] > 0).mean() * 100
    avg_real = closed_df["realized_pnl_pct"].mean()
else:
    win_rate, avg_real = 0.0, 0.0
c3.metric("已平倉勝率", f"{win_rate:.0f}%")
c4.metric("已平倉均報酬", f"{avg_real:+.2f}%")

# ===================================================================
# 2. 持有中部位
# ===================================================================
st.subheader("持有中部位")
if open_df.empty:
    st.info("目前無持有中部位。")
else:
    show_cols = [
        "report_date", "stock_id", "stock_name", "entry_price",
        "current_price", "unrealized_pnl_pct", "holding_days", "peak_price",
    ]
    show = open_df[[c for c in show_cols if c in open_df.columns]].copy()
    show = show.sort_values("unrealized_pnl_pct", ascending=False)
    st.dataframe(show, use_container_width=True, hide_index=True)

# ===================================================================
# 3. 已平倉部位 + 出場原因
# ===================================================================
st.subheader("已平倉部位")
if closed_df.empty:
    st.info("尚無已平倉部位。")
else:
    col_a, col_b = st.columns([1, 1])
    with col_a:
        reason_counts = closed_df["exit_reason"].value_counts().reset_index()
        reason_counts.columns = ["出場原因", "次數"]
        fig = px.bar(reason_counts, x="出場原因", y="次數", title="出場原因分佈")
        st.plotly_chart(fig, use_container_width=True)
    with col_b:
        fig2 = px.histogram(
            closed_df, x="realized_pnl_pct", nbins=20, title="已實現損益分佈 (%)"
        )
        st.plotly_chart(fig2, use_container_width=True)

    closed_cols = [
        "report_date", "stock_id", "stock_name", "entry_price", "exit_date",
        "exit_price", "realized_pnl_pct", "holding_days", "exit_reason",
    ]
    show_closed = closed_df[[c for c in closed_cols if c in closed_df.columns]].copy()
    show_closed = show_closed.sort_values("exit_date", ascending=False)
    st.dataframe(show_closed, use_container_width=True, hide_index=True)
