"""
Page 11: 機器學習選股 — LightGBM 因子非線性組合
"""

import sys
from datetime import date, timedelta
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
    load_chip_institutional_multi,
    load_daily_price_multi,
    load_stock_per_multi,
    load_top_volume_stocks,
)
from analysis.utils.ml_stock_picker import (
    MLModelResult,
    prepare_features,
    predict_scores,
    train_lightgbm,
    walk_forward_backtest,
)

st.set_page_config(page_title="機器學習選股", page_icon="🤖", layout="wide")
st.title("🤖 機器學習選股")

# --- Sidebar ---
st.sidebar.header("模型設定")

pool_option = st.sidebar.radio("股票池", ["成交量前 50", "成交量前 100", "自選"],
                                key="ml_pool")
if pool_option == "自選":
    custom_ids = st.sidebar.text_area(
        "輸入股票代號（逗號分隔）",
        value="2330,2317,2454,2881,2882,2412,3008,2308",
        key="ml_custom_ids",
    )
    stock_ids = [s.strip() for s in custom_ids.split(",") if s.strip()]
else:
    n_stocks = 50 if pool_option == "成交量前 50" else 100
    stock_ids = load_top_volume_stocks(n=n_stocks, lookback_days=30)

forward_days = st.sidebar.selectbox("前瞻天數", [5, 10, 20], index=0, key="ml_forward")
n_quantiles = st.sidebar.selectbox("分位數", [3, 5], index=0, key="ml_quantiles")

use_fundamental = st.sidebar.checkbox("使用基本面因子", value=True, key="ml_fund")
use_chip = st.sidebar.checkbox("使用籌碼面因子", value=True, key="ml_chip")

date_range = st.sidebar.selectbox(
    "訓練資料範圍",
    ["近 1 年", "近 2 年", "近 3 年"],
    index=1,
    key="ml_date_range",
)
lookback_map = {"近 1 年": 365, "近 2 年": 730, "近 3 年": 1095}
start_date = (date.today() - timedelta(days=lookback_map[date_range])).isoformat()

run_btn = st.sidebar.button("訓練模型", type="primary", use_container_width=True)

# --- Main ---
if run_btn:
    if not stock_ids:
        st.error("股票池為空。")
        st.stop()

    with st.spinner("載入資料中..."):
        price_df = load_daily_price_multi(stock_ids, start_date)
        per_df = load_stock_per_multi(stock_ids, start_date) if use_fundamental else None
        chip_df = load_chip_institutional_multi(stock_ids, start_date) if use_chip else None

    if price_df.empty:
        st.error("無法載入價格資料。")
        st.stop()

    with st.spinner("準備特徵..."):
        X, y, meta = prepare_features(
            price_df, per_df, chip_df,
            forward_days=forward_days,
            n_quantiles=n_quantiles,
        )

    if X.empty:
        st.error("特徵準備失敗，資料不足。")
        st.stop()

    st.info(f"特徵矩陣: {X.shape[0]} 樣本 × {X.shape[1]} 特徵")

    with st.spinner("訓練 LightGBM 模型..."):
        # 80/20 時序分割
        split_idx = int(len(X) * 0.8)
        X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
        y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]

        ml_result = train_lightgbm(X_train, y_train, X_val, y_val)

    st.session_state["ml_result"] = ml_result
    st.session_state["ml_X"] = X
    st.session_state["ml_y"] = y
    st.session_state["ml_meta"] = meta
    st.session_state["ml_params"] = {
        "forward_days": forward_days,
        "n_quantiles": n_quantiles,
    }

if "ml_result" not in st.session_state:
    st.info("請在左側面板設定參數後，點擊「訓練模型」。")
    st.stop()

ml_result = st.session_state["ml_result"]
X = st.session_state["ml_X"]
y = st.session_state["ml_y"]
meta = st.session_state["ml_meta"]
ml_params = st.session_state["ml_params"]

if ml_result.model is None:
    st.error("模型訓練失敗。")
    st.stop()

tab1, tab2, tab3 = st.tabs(["📊 訓練結果", "🏆 選股推薦", "📈 Walk-Forward 回測"])

# ===== Tab 1: 訓練結果 =====
with tab1:
    # 績效指標
    st.subheader("模型績效")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("訓練準確率", f"{ml_result.train_metrics.get('accuracy', 0):.2%}")
    c2.metric("訓練 F1", f"{ml_result.train_metrics.get('f1', 0):.2%}")
    c3.metric("驗證準確率", f"{ml_result.val_metrics.get('accuracy', 0):.2%}")
    c4.metric("驗證 F1", f"{ml_result.val_metrics.get('f1', 0):.2%}")

    # 特徵重要性
    st.subheader("特徵重要性 (Feature Importance)")
    if not ml_result.feature_importance.empty:
        fig_imp = px.bar(
            ml_result.feature_importance.sort_values("importance", ascending=True),
            x="importance", y="feature_name",
            orientation="h",
            color="importance",
            color_continuous_scale="Viridis",
            labels={"importance": "重要性 (Gain)", "feature_name": "特徵"},
        )
        fig_imp.update_layout(
            template="plotly_dark",
            height=max(300, len(ml_result.feature_importance) * 30),
        )
        st.plotly_chart(fig_imp, use_container_width=True)

    # 混淆矩陣概念（使用驗證集預測）
    st.subheader("驗證集預測分佈")
    split_idx = int(len(X) * 0.8)
    X_val = X.iloc[split_idx:]
    y_val = y.iloc[split_idx:]
    if not X_val.empty:
        val_pred = ml_result.model.predict(X_val)
        if val_pred.ndim == 2:
            pred_labels = val_pred.argmax(axis=1)
        else:
            pred_labels = (val_pred > 0.5).astype(int)

        confusion = pd.crosstab(
            pd.Series(y_val.values, name="實際"),
            pd.Series(pred_labels, name="預測"),
        )
        fig_cm = px.imshow(
            confusion.values,
            x=[f"預測 Q{i}" for i in confusion.columns],
            y=[f"實際 Q{i}" for i in confusion.index],
            text_auto=True,
            color_continuous_scale="Blues",
        )
        fig_cm.update_layout(template="plotly_dark", height=350)
        st.plotly_chart(fig_cm, use_container_width=True)

# ===== Tab 2: 選股推薦 =====
with tab2:
    st.subheader("最新截面預測排序")
    st.caption("依據最近一期的因子資料進行預測排序")

    # 取最新日期的資料
    if "date" in meta.columns:
        latest_date = meta["date"].max()
        latest_mask = meta["date"] == latest_date
        X_latest = X.loc[latest_mask.values]
        meta_latest = meta.loc[latest_mask]

        if not X_latest.empty:
            pred_result = predict_scores(ml_result.model, X_latest)

            display = meta_latest[["stock_id"]].copy().reset_index(drop=True)
            display["預測分數"] = pred_result["pred_score"].values
            display["預測分位"] = pred_result["pred_label"].values
            display = display.sort_values("預測分數", ascending=False).reset_index(drop=True)
            display["排名"] = range(1, len(display) + 1)

            # 標記推薦
            n_q = ml_params["n_quantiles"]
            display["推薦"] = display["預測分位"].apply(
                lambda x: "買入" if x == n_q - 1 else ("賣出" if x == 0 else "觀望")
            )

            st.dataframe(
                display[["排名", "stock_id", "預測分數", "預測分位", "推薦"]],
                use_container_width=True,
                hide_index=True,
            )

            # 推薦摘要
            buy_stocks = display[display["推薦"] == "買入"]["stock_id"].tolist()
            sell_stocks = display[display["推薦"] == "賣出"]["stock_id"].tolist()
            c1, c2 = st.columns(2)
            c1.success(f"買入推薦 ({len(buy_stocks)} 支): {', '.join(buy_stocks[:10])}")
            c2.error(f"賣出推薦 ({len(sell_stocks)} 支): {', '.join(sell_stocks[:10])}")
        else:
            st.warning("無最新截面資料。")
    else:
        st.warning("缺少日期資訊。")

# ===== Tab 3: Walk-Forward 回測 =====
with tab3:
    st.subheader("Walk-Forward 回測")
    st.caption("滾動訓練窗口，模擬真實投資環境")

    wf_train_window = st.slider("訓練窗口（天）", 60, 500, 252, key="wf_window")
    wf_step = st.slider("步進天數", 5, 60, 20, key="wf_step")

    if st.button("執行 Walk-Forward", key="wf_run"):
        with st.spinner("執行 Walk-Forward 回測..."):
            wf_dates = meta["date"] if "date" in meta.columns else pd.Series(range(len(X)))
            wf_result = walk_forward_backtest(
                X, y, wf_dates,
                train_window=wf_train_window,
                step=wf_step,
            )

        if wf_result.empty:
            st.error("Walk-Forward 回測失敗，資料不足。")
        else:
            # 準確率
            correct = (wf_result["pred_label"] == wf_result["actual_label"]).mean()
            st.metric("Walk-Forward 準確率", f"{correct:.2%}")

            # 各分位的預測分佈
            fig_dist = px.histogram(
                wf_result, x="pred_score", color="actual_label",
                barmode="overlay", opacity=0.7,
                labels={"pred_score": "預測分數", "actual_label": "實際分位"},
                title="預測分數 vs 實際分位分佈",
            )
            fig_dist.update_layout(template="plotly_dark", height=400)
            st.plotly_chart(fig_dist, use_container_width=True)

            # 每期準確率追蹤
            if "date" in wf_result.columns:
                wf_result["correct"] = (wf_result["pred_label"] == wf_result["actual_label"]).astype(int)
                daily_acc = wf_result.groupby("date")["correct"].mean().reset_index()
                daily_acc.columns = ["date", "accuracy"]
                fig_acc = go.Figure()
                fig_acc.add_trace(go.Scatter(
                    x=daily_acc["date"], y=daily_acc["accuracy"],
                    mode="lines", name="準確率",
                ))
                fig_acc.add_hline(y=1.0 / ml_params["n_quantiles"],
                                 line_dash="dash", line_color="red",
                                 annotation_text="隨機基準")
                fig_acc.update_layout(
                    template="plotly_dark", height=350,
                    title="Walk-Forward 準確率追蹤",
                    yaxis_title="準確率", xaxis_title="日期",
                )
                st.plotly_chart(fig_acc, use_container_width=True)
