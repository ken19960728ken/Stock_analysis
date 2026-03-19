"""
Granger 因果供應鏈自動發現 — 數據驅動的產業連動分析

使用 Granger 因果檢定自動偵測次產業間的營收連動關係，
建構因果有向圖（DAG），推導上下游順序。
"""

import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import grangercausalitytests


def build_industry_series(
    revenue_df: pd.DataFrame,
    industry_map: pd.DataFrame,
) -> dict[str, pd.Series]:
    """將月營收資料按次產業聚合為月度 YoY 時間序列

    Args:
        revenue_df: 月營收 (stock_id, date, month_revenue_year_on_year)
        industry_map: (stock_id, sub_industry)

    Returns:
        Dict[sub_industry_name, pd.Series(index=Period, values=avg_yoy)]
    """
    if revenue_df.empty or industry_map.empty:
        return {}

    if "sub_industry" not in industry_map.columns:
        return {}

    df = revenue_df.merge(
        industry_map[["stock_id", "sub_industry"]],
        on="stock_id", how="inner",
    )
    df = df.dropna(subset=["sub_industry"])
    if df.empty or "month_revenue_year_on_year" not in df.columns:
        return {}

    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.to_period("M")
    df["month_revenue_year_on_year"] = pd.to_numeric(
        df["month_revenue_year_on_year"], errors="coerce"
    )

    monthly = df.groupby(["sub_industry", "month"])[
        "month_revenue_year_on_year"
    ].mean()

    result = {}
    for sub_ind in monthly.index.get_level_values(0).unique():
        series = monthly.loc[sub_ind].sort_index().dropna()
        if len(series) >= 4:  # 至少 4 個月才有意義
            result[sub_ind] = series

    return result


def granger_pairwise(
    series_dict: dict[str, pd.Series],
    max_lag: int = 3,
    p_threshold: float = 0.05,
) -> pd.DataFrame:
    """對所有次產業 pair 執行 Granger 因果檢定

    Args:
        series_dict: {sub_industry: Series(index=Period, values=yoy)}
        max_lag: 最大滯後期數
        p_threshold: 顯著性門檻

    Returns:
        DataFrame[source, target, lag, f_stat, p_value]
        source Granger-causes target（source 領先 target）
    """
    names = list(series_dict.keys())
    if len(names) < 2:
        return pd.DataFrame(columns=["source", "target", "lag", "f_stat", "p_value"])

    results = []
    for i, src in enumerate(names):
        for j, tgt in enumerate(names):
            if i == j:
                continue
            s_src = series_dict[src]
            s_tgt = series_dict[tgt]

            # 對齊時間
            common = s_src.index.intersection(s_tgt.index)
            if len(common) < max_lag + 3:
                continue

            data = pd.DataFrame({
                "target": s_tgt.loc[common].values,
                "source": s_src.loc[common].values,
            })

            # Granger 檢定需要 target 在前、source 在後
            try:
                test_result = grangercausalitytests(
                    data[["target", "source"]], maxlag=max_lag, verbose=False
                )
            except Exception:
                continue

            # 取所有 lag 中最顯著的
            best_p = 1.0
            best_lag = 0
            best_f = 0.0
            for lag_val in range(1, max_lag + 1):
                if lag_val not in test_result:
                    continue
                f_test = test_result[lag_val][0]["ssr_ftest"]
                p_val = f_test[1]
                f_stat = f_test[0]
                if p_val < best_p:
                    best_p = p_val
                    best_lag = lag_val
                    best_f = f_stat

            if best_p < p_threshold:
                results.append({
                    "source": src,
                    "target": tgt,
                    "lag": best_lag,
                    "f_stat": round(best_f, 3),
                    "p_value": round(best_p, 6),
                })

    if not results:
        return pd.DataFrame(columns=["source", "target", "lag", "f_stat", "p_value"])

    return pd.DataFrame(results).sort_values("p_value").reset_index(drop=True)
