"""
推薦命中率儀表板 — 追蹤每日選股報告的歷史績效

⚠️ 開發模式：目前讀取本地 SQLite（data/recommendation_local.db）
   正式環境：設環境變數 RECOMMENDATION_DB_SOURCE=supabase 切換到真實資料

區塊：
  1. 整體績效概覽（metrics + 報酬分佈直方圖）
  2. 策略拆分命中率（表格 + 長條圖）
  3. 排名 vs 績效（散點圖 + 分組對比）
  4. 時間趨勢（折線圖 + 版本變更標記）
"""

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.utils.recommendation_db import (
    load_all_recommendations,
    load_version_timeline,
)

st.set_page_config(page_title="推薦追蹤", page_icon="🎯", layout="wide")
st.title("推薦命中率儀表板")

data_source = os.getenv("RECOMMENDATION_DB_SOURCE", "sqlite")
if data_source == "sqlite":
    st.caption("⚠️ 開發模式 — 使用本地 SQLite 資料（含模擬資料）。正式環境請設 `RECOMMENDATION_DB_SOURCE=supabase`。")


# ===================================================================
# Sidebar 篩選
# ===================================================================

st.sidebar.header("篩選條件")

df_all = load_all_recommendations()
if df_all.empty:
    st.warning("尚無推薦記錄。請先執行 `uv run python scripts/seed_recommendation_data.py` 建立種子資料。")
    st.stop()

df_all["report_date"] = pd.to_datetime(df_all["report_date"])

date_min = df_all["report_date"].min().date()
date_max = df_all["report_date"].max().date()
date_range = st.sidebar.date_input(
    "日期範圍", value=(date_min, date_max), min_value=date_min, max_value=date_max
)

if isinstance(date_range, tuple) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date, end_date = date_min, date_max

max_rank = int(df_all["rank"].max()) if "rank" in df_all.columns and df_all["rank"].notna().any() else 20
rank_limit = st.sidebar.slider("排名範圍", 1, max_rank, max_rank)

exclude_sim = False
if "is_simulated" in df_all.columns and df_all["is_simulated"].any():
    exclude_sim = st.sidebar.checkbox("排除模擬資料", value=False)

# 過濾
df = df_all[
    (df_all["report_date"].dt.date >= start_date)
    & (df_all["report_date"].dt.date <= end_date)
    & (df_all["rank"] <= rank_limit)
].copy()

if exclude_sim and "is_simulated" in df.columns:
    df = df[df["is_simulated"] == 0]

if df.empty:
    st.info("篩選條件下無資料")
    st.stop()


# ===================================================================
# 區塊 1：整體績效概覽
# ===================================================================

st.header("整體績效概覽")

col1, col2, col3, col4, col5 = st.columns(5)

n_records = len(df)
n_days = df["report_date"].nunique()

for col, t_label, t_col in [
    (col1, "T+5", "return_t5"),
    (col2, "T+10", "return_t10"),
    (col3, "T+20", "return_t20"),
]:
    valid = df[t_col].dropna()
    if valid.empty:
        col.metric(f"{t_label} 平均報酬", "—")
    else:
        avg = valid.mean()
        wr = (valid > 0).mean() * 100
        col.metric(f"{t_label} 平均報酬", f"{avg:+.2f}%")
        col.metric(f"{t_label} 勝率", f"{wr:.0f}%")

col4.metric("推薦筆數", f"{n_records}")
col5.metric("追蹤天數", f"{n_days}")

# 報酬分佈直方圖
st.subheader("報酬分佈")
hist_data = []
for t_label, t_col in [("T+5", "return_t5"), ("T+10", "return_t10"), ("T+20", "return_t20")]:
    valid = df[[t_col]].dropna().copy()
    valid.columns = ["return_pct"]
    valid["期間"] = t_label
    hist_data.append(valid)

if hist_data:
    hist_df = pd.concat(hist_data)
    fig_hist = px.histogram(
        hist_df, x="return_pct", color="期間", barmode="overlay",
        nbins=30, opacity=0.6,
        labels={"return_pct": "報酬率 (%)", "期間": ""},
        title="推薦股票報酬率分佈",
    )
    fig_hist.add_vline(x=0, line_dash="dash", line_color="gray")
    st.plotly_chart(fig_hist, use_container_width=True)


# ===================================================================
# 區塊 2：策略拆分命中率
# ===================================================================

st.header("策略拆分命中率")

has_t5 = df[df["return_t5"].notna()].copy()
if has_t5.empty:
    st.info("尚無 T+5 績效資料")
else:
    strategy_stats: dict[str, list[float]] = {}
    for _, row in has_t5.iterrows():
        votes = row.get("strategy_votes")
        if not isinstance(votes, dict):
            continue
        for name, v in votes.items():
            if isinstance(v, dict) and v.get("recent_score", 0) > 0:
                strategy_stats.setdefault(name, []).append(row["return_t5"])

    strat_rows = []
    for name in sorted(strategy_stats, key=lambda x: -len(strategy_stats[x])):
        returns = strategy_stats[name]
        count = len(returns)
        if count < 2:
            continue
        wr = sum(1 for r in returns if r > 0) / count * 100
        avg = sum(returns) / count
        strat_rows.append({
            "策略": name, "推薦次數": count,
            "T+5 勝率": f"{wr:.0f}%", "T+5 均報酬": f"{avg:+.2f}%",
            "_wr": wr, "_avg": avg,
        })

    if strat_rows:
        strat_df = pd.DataFrame(strat_rows)

        st.dataframe(
            strat_df[["策略", "推薦次數", "T+5 勝率", "T+5 均報酬"]],
            use_container_width=True, hide_index=True,
        )

        fig_strat = px.bar(
            strat_df.sort_values("_wr", ascending=True),
            x="_wr", y="策略", orientation="h",
            labels={"_wr": "T+5 勝率 (%)", "策略": ""},
            title="各策略 T+5 勝率",
            text="_wr",
        )
        fig_strat.update_traces(texttemplate="%{text:.0f}%", textposition="outside")
        fig_strat.add_vline(x=50, line_dash="dash", line_color="gray", annotation_text="50%")
        st.plotly_chart(fig_strat, use_container_width=True)
    else:
        st.info("策略樣本數不足")


# ===================================================================
# 區塊 3：排名 vs 績效
# ===================================================================

st.header("排名 vs 績效")

rank_df = df[["rank", "return_t5"]].dropna()
if rank_df.empty:
    st.info("尚無排名績效資料")
else:
    fig_scatter = px.scatter(
        rank_df, x="rank", y="return_t5",
        labels={"rank": "推薦排名", "return_t5": "T+5 報酬率 (%)"},
        title="推薦排名 vs T+5 報酬率",
        trendline="ols",
        opacity=0.6,
    )
    fig_scatter.add_hline(y=0, line_dash="dash", line_color="gray")

    if len(rank_df) >= 3:
        from scipy.stats import linregress
        slope, intercept, r_value, p_value, std_err = linregress(rank_df["rank"], rank_df["return_t5"])
        r_sq = r_value ** 2
        st.caption(f"線性回歸：r² = {r_sq:.3f}, slope = {slope:.3f}, p = {p_value:.3f}")

    st.plotly_chart(fig_scatter, use_container_width=True)

    def _rank_group(r):
        if r <= 5:
            return "Top 5"
        elif r <= 10:
            return "Top 6-10"
        else:
            return "Top 11+"

    rank_df = rank_df.copy()
    rank_df["分組"] = rank_df["rank"].apply(_rank_group)
    group_stats = rank_df.groupby("分組")["return_t5"].agg(["mean", "count"]).reset_index()
    group_stats.columns = ["分組", "平均報酬", "樣本數"]
    order = {"Top 5": 0, "Top 6-10": 1, "Top 11+": 2}
    group_stats["_order"] = group_stats["分組"].map(order)
    group_stats = group_stats.sort_values("_order")

    fig_group = px.bar(
        group_stats, x="分組", y="平均報酬",
        text="平均報酬",
        labels={"平均報酬": "T+5 平均報酬 (%)", "分組": ""},
        title="排名分組 T+5 平均報酬對比",
    )
    fig_group.update_traces(texttemplate="%{text:+.2f}%", textposition="outside")
    fig_group.add_hline(y=0, line_dash="dash", line_color="gray")
    st.plotly_chart(fig_group, use_container_width=True)


# ===================================================================
# 區塊 4：時間趨勢
# ===================================================================

st.header("時間趨勢")

time_df = df[["report_date", "return_t5"]].dropna()
if time_df.empty:
    st.info("尚無時序資料")
else:
    daily_avg = time_df.groupby("report_date")["return_t5"].mean().reset_index()
    daily_avg.columns = ["date", "avg_return"]
    daily_avg = daily_avg.sort_values("date")

    if len(daily_avg) >= 5:
        daily_avg["MA5"] = daily_avg["avg_return"].rolling(5, min_periods=1).mean()
    else:
        daily_avg["MA5"] = daily_avg["avg_return"]

    fig_trend = go.Figure()
    fig_trend.add_trace(go.Scatter(
        x=daily_avg["date"], y=daily_avg["avg_return"],
        mode="markers+lines", name="每日平均 T+5 報酬",
        line=dict(color="lightblue"), marker=dict(size=6),
    ))
    fig_trend.add_trace(go.Scatter(
        x=daily_avg["date"], y=daily_avg["MA5"],
        mode="lines", name="5 日滾動均線",
        line=dict(color="blue", width=2),
    ))
    fig_trend.add_hline(y=0, line_dash="dash", line_color="gray")

    ver_df = load_version_timeline()
    if not ver_df.empty:
        ver_df["report_date"] = pd.to_datetime(ver_df["report_date"])
        for _, vrow in ver_df.iterrows():
            commit_short = str(vrow["git_commit"])[:7]
            fig_trend.add_vline(
                x=vrow["report_date"], line_dash="dot", line_color="orange",
                annotation_text=commit_short,
                annotation_position="top",
            )

    fig_trend.update_layout(
        title="推薦績效時間趨勢",
        xaxis_title="報告日期",
        yaxis_title="平均 T+5 報酬率 (%)",
    )
    st.plotly_chart(fig_trend, use_container_width=True)
