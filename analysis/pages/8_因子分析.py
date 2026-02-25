"""
Page 8: 因子分析 — IC 回測驗證、因子相關性矩陣、因子有效性排行
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = str(Path(__file__).resolve().parents[2])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from analysis.utils.charts import create_correlation_heatmap
from analysis.utils.data_loader import (
    load_chip_institutional_multi,
    load_daily_price_multi,
    load_stock_per_multi,
    load_top_volume_stocks,
)
from analysis.utils.dynamic_weights import rolling_ic_weights
from analysis.utils.factor_engine import factor_correlation_matrix, ic_series, rolling_ic_mean
from analysis.utils.indicators import (
    add_bollinger,
    add_kd,
    add_ma,
    add_macd,
    add_rsi,
)

st.set_page_config(page_title="因子分析", page_icon="📊", layout="wide")
st.title("📊 因子分析")

# ---------------------------------------------------------------------------
# 因子定義
# ---------------------------------------------------------------------------
FACTOR_DEFINITIONS = {
    # 技術面
    "RSI(14)": {"type": "技術面", "desc": "相對強弱指標 14 日"},
    "MACD Histogram": {"type": "技術面", "desc": "MACD 柱狀圖"},
    "MA20 方向": {"type": "技術面", "desc": "MA20 五日斜率"},
    "KD-K值": {"type": "技術面", "desc": "KD 隨機指標 K 值"},
    "Bollinger %B": {"type": "技術面", "desc": "布林通道 %B"},
    "成交量比": {"type": "技術面", "desc": "成交量 / 20 日均量"},
    # 基本面
    "PER": {"type": "基本面", "desc": "本益比"},
    "PBR": {"type": "基本面", "desc": "股價淨值比"},
    "殖利率": {"type": "基本面", "desc": "現金殖利率"},
    # 籌碼面
    "法人淨買超": {"type": "籌碼面", "desc": "三大法人淨買超合計"},
    "外資淨買超": {"type": "籌碼面", "desc": "外資淨買超"},
}

DEFAULT_FACTORS = ["RSI(14)", "MACD Histogram", "PER", "法人淨買超"]


# ---------------------------------------------------------------------------
# 技術指標計算
# ---------------------------------------------------------------------------
def _compute_technical_factors(price_df: pd.DataFrame) -> pd.DataFrame:
    """對多股價格資料逐股計算技術面因子，回傳寬表。"""
    results = []
    for sid, grp in price_df.groupby("stock_id"):
        g = grp.sort_values("date").copy()
        if len(g) < 30:
            continue
        g = add_rsi(g)
        g = add_macd(g)
        g = add_ma(g, periods=[20])
        g = add_kd(g)
        g = add_bollinger(g)

        g["RSI(14)"] = g["RSI"]
        g["MACD Histogram"] = g["MACD_histogram"]
        g["MA20 方向"] = g["MA20"].pct_change(5)
        g["KD-K值"] = g["K"]
        g["Bollinger %B"] = g["BB_pct"]
        vol_ma20 = g["volume"].rolling(20).mean()
        g["成交量比"] = g["volume"] / vol_ma20.replace(0, np.nan)

        results.append(
            g[["date", "stock_id", "close",
               "RSI(14)", "MACD Histogram", "MA20 方向",
               "KD-K值", "Bollinger %B", "成交量比"]]
        )
    if not results:
        return pd.DataFrame()
    return pd.concat(results, ignore_index=True)


def _compute_chip_factors(chip_df: pd.DataFrame) -> pd.DataFrame:
    """計算籌碼面因子。"""
    if chip_df.empty:
        return pd.DataFrame()
    df = chip_df.copy()
    # 法人淨買超 = 外資 + 投信 + 自營
    buy_cols = [c for c in df.columns if c.endswith("_buy")]
    sell_cols = [c for c in df.columns if c.endswith("_sell")]
    if buy_cols and sell_cols:
        df["法人淨買超"] = sum(df[c] for c in buy_cols) - sum(df[c] for c in sell_cols)
    # 外資淨買超
    if "foreign_investors_buy" in df.columns and "foreign_investors_sell" in df.columns:
        df["外資淨買超"] = df["foreign_investors_buy"] - df["foreign_investors_sell"]
    return df[["date", "stock_id", "法人淨買超", "外資淨買超"]].dropna(
        subset=["法人淨買超"], how="all"
    )


def _compute_fundamental_factors(per_df: pd.DataFrame) -> pd.DataFrame:
    """整理基本面因子。"""
    if per_df.empty:
        return pd.DataFrame()
    df = per_df.copy()
    rename = {"per": "PER", "pbr": "PBR", "dividend_yield": "殖利率"}
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    cols = ["date", "stock_id"] + [v for v in rename.values() if v in df.columns]
    return df[cols]


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.sidebar.header("分析設定")

# 股票池選擇
pool_option = st.sidebar.radio("股票池", ["成交量前 50", "成交量前 100", "自選"])
if pool_option == "自選":
    custom_ids = st.sidebar.text_area(
        "輸入股票代號（逗號分隔）",
        value="2330,2317,2454,2881,2882",
    )
    stock_ids = [s.strip() for s in custom_ids.split(",") if s.strip()]
else:
    n_stocks = 50 if pool_option == "成交量前 50" else 100
    stock_ids = load_top_volume_stocks(n=n_stocks, lookback_days=30)
    if not stock_ids:
        st.warning("無法取得股票池，請改用自選模式。")
        st.stop()

# 限制上限 100 支
if len(stock_ids) > 100:
    stock_ids = stock_ids[:100]

st.sidebar.caption(f"股票池: {len(stock_ids)} 支")

# 因子選擇
selected_factors = st.sidebar.multiselect(
    "分析因子",
    list(FACTOR_DEFINITIONS.keys()),
    default=DEFAULT_FACTORS,
)
if not selected_factors:
    st.warning("請至少選擇一個因子。")
    st.stop()

# 前瞻天數
forward_days = st.sidebar.selectbox("前瞻天數", [5, 10, 20], index=0)

# 日期範圍
today = date.today()
date_range = st.sidebar.selectbox(
    "日期範圍",
    ["近 6 個月", "近 1 年", "近 2 年"],
    index=1,
)
lookback_map = {"近 6 個月": 180, "近 1 年": 365, "近 2 年": 730}
start_date = (today - timedelta(days=lookback_map[date_range])).isoformat()

# 執行按鈕
run_analysis = st.sidebar.button("🚀 執行分析", type="primary", use_container_width=True)


# ---------------------------------------------------------------------------
# 主要計算邏輯
# ---------------------------------------------------------------------------
def run_factor_analysis():
    """載入資料 → 計算因子 → 存入 session_state。"""
    progress = st.progress(0, text="載入價格資料...")

    # 判斷需要載入哪些資料
    need_tech = any(FACTOR_DEFINITIONS[f]["type"] == "技術面" for f in selected_factors)
    need_fund = any(FACTOR_DEFINITIONS[f]["type"] == "基本面" for f in selected_factors)
    need_chip = any(FACTOR_DEFINITIONS[f]["type"] == "籌碼面" for f in selected_factors)

    # 1. 載入價格資料（IC 計算永遠需要 close）
    price_df = load_daily_price_multi(stock_ids, start_date)
    if price_df.empty:
        st.error("無法載入價格資料，請檢查資料庫連線。")
        return
    progress.progress(25, text="計算技術指標...")

    # 2. 計算技術面因子
    tech_df = _compute_technical_factors(price_df) if need_tech else pd.DataFrame()
    progress.progress(40, text="載入基本面資料...")

    # 3. 基本面因子
    fund_df = pd.DataFrame()
    if need_fund:
        per_raw = load_stock_per_multi(stock_ids, start_date)
        fund_df = _compute_fundamental_factors(per_raw)
    progress.progress(55, text="載入籌碼面資料...")

    # 4. 籌碼面因子
    chip_factor_df = pd.DataFrame()
    if need_chip:
        chip_raw = load_chip_institutional_multi(stock_ids, start_date)
        chip_factor_df = _compute_chip_factors(chip_raw)
    progress.progress(70, text="合併因子資料...")

    # 5. 合併為寬表
    # 基底：每支股票的 date + stock_id + close
    base = price_df[["date", "stock_id", "close"]].copy()

    if not tech_df.empty:
        tech_cols = ["date", "stock_id"] + [
            f for f in selected_factors if f in tech_df.columns
        ]
        base = base.merge(tech_df[tech_cols], on=["date", "stock_id"], how="left")

    if not fund_df.empty:
        fund_cols = ["date", "stock_id"] + [
            f for f in selected_factors if f in fund_df.columns
        ]
        base = base.merge(fund_df[fund_cols], on=["date", "stock_id"], how="left")
        # forward fill 基本面資料（低頻）
        for col in fund_cols[2:]:
            base[col] = base.groupby("stock_id")[col].ffill()

    if not chip_factor_df.empty:
        chip_cols = ["date", "stock_id"] + [
            f for f in selected_factors if f in chip_factor_df.columns
        ]
        base = base.merge(chip_factor_df[chip_cols], on=["date", "stock_id"], how="left")

    progress.progress(85, text="計算 IC 序列...")

    # 6. 計算各因子 IC 序列
    ic_results = {}
    return_df = base[["date", "stock_id", "close"]].copy()
    factor_cols_in_data = [f for f in selected_factors if f in base.columns]

    for factor_name in factor_cols_in_data:
        factor_df = base[["date", "stock_id", factor_name, "close"]].dropna(
            subset=[factor_name]
        )
        if factor_df.empty or len(factor_df["stock_id"].unique()) < 5:
            continue
        ic_df = ic_series(factor_df, return_df, factor_name, forward_days)
        if not ic_df.empty:
            ic_results[factor_name] = ic_df

    progress.progress(100, text="完成！")

    # 存入 session_state
    st.session_state["fa_wide_table"] = base
    st.session_state["fa_ic_results"] = ic_results
    st.session_state["fa_factor_cols"] = factor_cols_in_data
    st.session_state["fa_selected_factors"] = selected_factors
    st.session_state["fa_forward_days"] = forward_days


# ---------------------------------------------------------------------------
# 執行分析
# ---------------------------------------------------------------------------
if run_analysis:
    run_factor_analysis()

if "fa_ic_results" not in st.session_state:
    st.info("請在左側面板設定參數後，點擊「執行分析」。")
    st.stop()

ic_results = st.session_state["fa_ic_results"]
factor_cols = st.session_state["fa_factor_cols"]
wide_table = st.session_state["fa_wide_table"]
fwd = st.session_state["fa_forward_days"]

if not ic_results:
    st.warning("所選因子在目前股票池中無足夠資料計算 IC，請更換因子或擴大股票池。")
    st.stop()

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab1, tab2, tab3, tab4 = st.tabs(["📈 IC 回測驗證", "🔗 因子相關性矩陣", "🏆 因子有效性排行", "🔄 動態權重追蹤"])

# ===== Tab 1: IC 回測驗證 =====
with tab1:
    factor_choice = st.selectbox(
        "選擇因子", list(ic_results.keys()), key="ic_factor_select"
    )
    ic_df = ic_results[factor_choice]

    if ic_df.empty or ic_df["ic"].isna().all():
        st.warning(f"因子 {factor_choice} 無有效 IC 資料。")
    else:
        # IC 統計卡片
        ic_vals = ic_df["ic"].dropna()
        mean_ic = ic_vals.mean()
        ic_std = ic_vals.std()
        ic_positive_ratio = (ic_vals > 0).mean()
        icir = mean_ic / ic_std if ic_std > 0 else 0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Mean IC", f"{mean_ic:.4f}")
        c2.metric("IC > 0 比率", f"{ic_positive_ratio:.1%}")
        c3.metric("IC Std", f"{ic_std:.4f}")
        c4.metric("ICIR (Mean/Std)", f"{icir:.4f}")

        # IC 柱狀圖
        colors = ["#26A69A" if v >= 0 else "#EF5350" for v in ic_df["ic"]]
        fig_ic = go.Figure()
        fig_ic.add_trace(go.Bar(
            x=ic_df["date"], y=ic_df["ic"],
            marker_color=colors, name="IC",
        ))
        fig_ic.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.5)
        fig_ic.add_hline(
            y=mean_ic, line_dash="dot", line_color="#4FC3F7",
            annotation_text=f"Mean IC: {mean_ic:.4f}",
        )
        fig_ic.update_layout(
            title=f"{factor_choice} — IC 時間序列 (前瞻 {fwd} 日)",
            template="plotly_dark", height=350,
            xaxis_title="日期", yaxis_title="IC",
            margin=dict(l=50, r=30, t=50, b=30),
        )
        st.plotly_chart(fig_ic, use_container_width=True)

        # 累積 IC 曲線
        fig_cum = go.Figure()
        fig_cum.add_trace(go.Scatter(
            x=ic_df["date"], y=ic_df["ic_cumsum"],
            mode="lines", name="累積 IC",
            line=dict(color="#4FC3F7", width=2),
            fill="tozeroy", fillcolor="rgba(79,195,247,0.1)",
        ))
        fig_cum.update_layout(
            title=f"{factor_choice} — 累積 IC",
            template="plotly_dark", height=300,
            xaxis_title="日期", yaxis_title="累積 IC",
            margin=dict(l=50, r=30, t=50, b=30),
        )
        st.plotly_chart(fig_cum, use_container_width=True)

# ===== Tab 2: 因子相關性矩陣 =====
with tab2:
    avail_factors = [f for f in factor_cols if f in wide_table.columns]
    if len(avail_factors) < 2:
        st.warning("需要至少 2 個因子才能計算相關性矩陣。")
    else:
        # 取各因子的截面均值序列（按日期）
        factor_series = {}
        for f in avail_factors:
            s = wide_table.groupby("date")[f].mean().dropna()
            if len(s) > 10:
                factor_series[f] = s

        if len(factor_series) < 2:
            st.warning("有效因子數不足，無法計算相關性。")
        else:
            corr_matrix = factor_correlation_matrix(factor_series)
            fig_corr = create_correlation_heatmap(corr_matrix, title="因子相關性矩陣")
            st.plotly_chart(fig_corr, use_container_width=True)

            # 高相關性警告
            high_corr_pairs = []
            for i in range(len(corr_matrix)):
                for j in range(i + 1, len(corr_matrix)):
                    val = corr_matrix.iloc[i, j]
                    if abs(val) > 0.7:
                        high_corr_pairs.append(
                            (corr_matrix.index[i], corr_matrix.columns[j], val)
                        )
            if high_corr_pairs:
                st.warning("**高相關性警告** — 以下因子對相關性 > 0.7，可能存在共線性：")
                for f1, f2, val in high_corr_pairs:
                    st.write(f"- **{f1}** ↔ **{f2}**: {val:.3f}")
            else:
                st.success("所有因子對相關性均在 ±0.7 以內，共線性風險低。")

# ===== Tab 3: 因子有效性排行 =====
with tab3:
    ranking_data = []
    for factor_name, ic_df in ic_results.items():
        ic_vals = ic_df["ic"].dropna()
        if len(ic_vals) < 5:
            continue
        mean_ic = ic_vals.mean()
        ic_std = ic_vals.std()
        ic_pos_ratio = (ic_vals > 0).mean()
        icir = mean_ic / ic_std if ic_std > 0 else 0.0

        # 有效性標籤
        abs_icir = abs(icir)
        if abs_icir > 0.5:
            label = "🟢 強"
        elif abs_icir > 0.3:
            label = "🟡 中"
        else:
            label = "🔴 弱"

        ranking_data.append({
            "因子名稱": factor_name,
            "類型": FACTOR_DEFINITIONS.get(factor_name, {}).get("type", "—"),
            "Mean IC": mean_ic,
            "IC>0 比率": ic_pos_ratio,
            "IC Std": ic_std,
            "ICIR": icir,
            "有效性": label,
        })

    if not ranking_data:
        st.warning("無足夠資料產生排行。")
    else:
        rank_df = pd.DataFrame(ranking_data)
        rank_df["|Mean IC|"] = rank_df["Mean IC"].abs()
        rank_df = rank_df.sort_values("|Mean IC|", ascending=False).drop(
            columns=["|Mean IC|"]
        )

        # 格式化顯示
        display_df = rank_df.copy()
        display_df["Mean IC"] = display_df["Mean IC"].map(lambda x: f"{x:.4f}")
        display_df["IC>0 比率"] = display_df["IC>0 比率"].map(lambda x: f"{x:.1%}")
        display_df["IC Std"] = display_df["IC Std"].map(lambda x: f"{x:.4f}")
        display_df["ICIR"] = display_df["ICIR"].map(lambda x: f"{x:.4f}")

        st.dataframe(
            display_df.reset_index(drop=True),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("""
        ---
        **判讀說明**
        - **Mean IC**: 因子值與未來報酬的 Spearman 相關係數均值。正值代表因子值越大，未來報酬越高。
        - **ICIR (IC Information Ratio)**: Mean IC / IC Std，衡量因子預測能力的穩定性。
        - **有效性**: |ICIR| > 0.5 → 強、0.3~0.5 → 中、< 0.3 → 弱。
        """)

# ===== Tab 4: 動態權重追蹤 =====
with tab4:
    if len(ic_results) < 2:
        st.warning("需要至少 2 個因子才能計算動態權重。")
    else:
        dw_method = st.selectbox(
            "權重計算方式",
            ["ICIR 加權", "IC 均值加權", "IC 指數衰減"],
            key="dw_method_select",
        )
        method_map = {"ICIR 加權": "icir", "IC 均值加權": "ic_mean", "IC 指數衰減": "ic_decay"}
        dw_lookback = st.slider("滾動窗口（天）", 20, 120, 60, key="dw_lookback")

        weights_df = rolling_ic_weights(
            ic_results,
            lookback=dw_lookback,
            method=method_map[dw_method],
        )

        if weights_df.empty:
            st.warning("無法計算動態權重，資料不足。")
        else:
            # 滾動 IC 趨勢折線圖
            st.subheader("各因子滾動 IC 趨勢")
            fig_rolling = go.Figure()
            for fname, ic_df in ic_results.items():
                rolling_mean = rolling_ic_mean(ic_df, window=dw_lookback)
                if not rolling_mean.empty:
                    fig_rolling.add_trace(go.Scatter(
                        x=rolling_mean.index, y=rolling_mean.values,
                        mode="lines", name=fname,
                    ))
            fig_rolling.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.3)
            fig_rolling.update_layout(
                template="plotly_dark", height=400,
                xaxis_title="日期", yaxis_title="滾動 IC 均值",
                margin=dict(l=50, r=30, t=30, b=30),
            )
            st.plotly_chart(fig_rolling, use_container_width=True)

            # 權重隨時間變化 stacked area chart
            st.subheader("因子權重變化")
            pivot_w = weights_df.pivot(index="date", columns="factor_name", values="weight").fillna(0)
            import plotly.express as px
            fig_area = px.area(
                pivot_w.reset_index(), x="date", y=pivot_w.columns.tolist(),
                labels={"value": "權重", "date": "日期"},
            )
            fig_area.update_layout(
                template="plotly_dark", height=400,
                yaxis_title="權重", legend_title="因子",
                margin=dict(l=50, r=30, t=30, b=30),
            )
            st.plotly_chart(fig_area, use_container_width=True)

            # 最新權重配置表
            st.subheader("當前最新權重配置")
            latest_date = weights_df["date"].max()
            latest_weights = weights_df[weights_df["date"] == latest_date].copy()
            latest_weights = latest_weights.sort_values("weight", ascending=False)
            latest_weights["weight"] = latest_weights["weight"].map(lambda x: f"{x:.2%}")
            st.dataframe(
                latest_weights[["factor_name", "weight"]].rename(
                    columns={"factor_name": "因子", "weight": "權重"}
                ).reset_index(drop=True),
                use_container_width=True,
                hide_index=True,
            )
