"""
產業輪動模組 — 營收動能 + 法人流向 → 產業強弱排序
"""

import numpy as np
import pandas as pd


def calc_industry_momentum(
    revenue_df: pd.DataFrame,
    industry_map: pd.DataFrame,
    lookback_months: int = 3,
) -> pd.DataFrame:
    """
    計算產業營收動能

    Parameters:
        revenue_df: 月營收資料 (stock_id, date, revenue, month_revenue_year_on_year)
        industry_map: (stock_id, industry_category)
        lookback_months: 回溯月數

    Returns:
        DataFrame[industry, avg_yoy, median_yoy, positive_ratio, momentum_score, rank]
    """
    if revenue_df.empty or industry_map.empty:
        return pd.DataFrame()

    # 合併產業分類
    df = revenue_df.merge(industry_map, on="stock_id", how="inner")
    if df.empty:
        return pd.DataFrame()

    # 取最近 N 個月
    df["date"] = pd.to_datetime(df["date"])
    latest_date = df["date"].max()
    cutoff = latest_date - pd.DateOffset(months=lookback_months)
    df = df[df["date"] >= cutoff]

    if df.empty or "month_revenue_year_on_year" not in df.columns:
        return pd.DataFrame()

    yoy_col = "month_revenue_year_on_year"
    df[yoy_col] = pd.to_numeric(df[yoy_col], errors="coerce")

    # 按產業彙總
    result = df.groupby("industry_category").agg(
        avg_yoy=(yoy_col, "mean"),
        median_yoy=(yoy_col, "median"),
        positive_ratio=(yoy_col, lambda x: (x > 0).mean()),
        stock_count=("stock_id", "nunique"),
    ).reset_index()

    result.rename(columns={"industry_category": "industry"}, inplace=True)

    # 動能分數 = 0.5 * avg_yoy_rank + 0.3 * positive_ratio_rank + 0.2 * median_yoy_rank
    for col in ["avg_yoy", "median_yoy", "positive_ratio"]:
        result[f"{col}_rank"] = result[col].rank(ascending=False)

    result["momentum_score"] = (
        0.5 * (1 - result["avg_yoy_rank"] / len(result)) +
        0.3 * (1 - result["positive_ratio_rank"] / len(result)) +
        0.2 * (1 - result["median_yoy_rank"] / len(result))
    )
    result["rank"] = result["momentum_score"].rank(ascending=False).astype(int)
    result = result.sort_values("rank")

    return result[["industry", "avg_yoy", "median_yoy", "positive_ratio",
                    "stock_count", "momentum_score", "rank"]]


def calc_industry_flow(
    chip_df: pd.DataFrame,
    industry_map: pd.DataFrame,
    lookback_days: int = 20,
) -> pd.DataFrame:
    """
    計算產業法人資金流向

    Parameters:
        chip_df: 三大法人買賣超 (stock_id, date, *_buy, *_sell)
        industry_map: (stock_id, industry_category)
        lookback_days: 回溯天數

    Returns:
        DataFrame[industry, total_net_buy, avg_net_buy, flow_score, rank]
    """
    if chip_df.empty or industry_map.empty:
        return pd.DataFrame()

    df = chip_df.merge(industry_map, on="stock_id", how="inner")
    if df.empty:
        return pd.DataFrame()

    df["date"] = pd.to_datetime(df["date"])
    latest_date = df["date"].max()
    cutoff = latest_date - pd.Timedelta(days=lookback_days)
    df = df[df["date"] >= cutoff]

    # 計算淨買超
    buy_cols = [c for c in df.columns if c.endswith("_buy")]
    sell_cols = [c for c in df.columns if c.endswith("_sell")]
    if buy_cols and sell_cols:
        df["net_buy"] = sum(df[c] for c in buy_cols) - sum(df[c] for c in sell_cols)
    elif "net_buy" not in df.columns:
        return pd.DataFrame()

    result = df.groupby("industry_category").agg(
        total_net_buy=("net_buy", "sum"),
        avg_net_buy=("net_buy", "mean"),
        stock_count=("stock_id", "nunique"),
    ).reset_index()

    result.rename(columns={"industry_category": "industry"}, inplace=True)

    result["flow_score"] = result["total_net_buy"].rank(ascending=False, pct=True)
    result["rank"] = result["total_net_buy"].rank(ascending=False).astype(int)
    result = result.sort_values("rank")

    return result[["industry", "total_net_buy", "avg_net_buy",
                    "stock_count", "flow_score", "rank"]]


def industry_composite_score(
    momentum: pd.DataFrame,
    flow: pd.DataFrame,
    m_weight: float = 0.5,
    f_weight: float = 0.5,
) -> pd.DataFrame:
    """
    合成產業綜合得分

    Returns:
        DataFrame[industry, momentum_rank, flow_rank, composite_score, final_rank]
    """
    if momentum.empty and flow.empty:
        return pd.DataFrame()

    if momentum.empty:
        flow = flow.copy()
        flow["final_rank"] = flow["rank"]
        flow["composite_score"] = flow["flow_score"]
        flow["momentum_rank"] = None
        flow["flow_rank"] = flow["rank"]
        return flow[["industry", "momentum_rank", "flow_rank", "composite_score", "final_rank"]]

    if flow.empty:
        momentum = momentum.copy()
        momentum["final_rank"] = momentum["rank"]
        momentum["composite_score"] = momentum["momentum_score"]
        momentum["momentum_rank"] = momentum["rank"]
        momentum["flow_rank"] = None
        return momentum[["industry", "momentum_rank", "flow_rank", "composite_score", "final_rank"]]

    merged = momentum[["industry", "rank", "momentum_score"]].merge(
        flow[["industry", "rank", "flow_score"]],
        on="industry",
        how="outer",
        suffixes=("_momentum", "_flow"),
    )

    # 填充缺失排名
    n = len(merged)
    merged["rank_momentum"] = merged["rank_momentum"].fillna(n)
    merged["rank_flow"] = merged["rank_flow"].fillna(n)
    merged["momentum_score"] = merged["momentum_score"].fillna(0)
    merged["flow_score"] = merged["flow_score"].fillna(0)

    merged["composite_score"] = (
        m_weight * merged["momentum_score"] +
        f_weight * merged["flow_score"]
    )

    merged["final_rank"] = merged["composite_score"].rank(ascending=False).astype(int)
    merged = merged.sort_values("final_rank")
    merged.rename(columns={"rank_momentum": "momentum_rank", "rank_flow": "flow_rank"},
                  inplace=True)

    return merged[["industry", "momentum_rank", "flow_rank",
                    "composite_score", "final_rank"]]


def industry_rotation_history(
    revenue_df: pd.DataFrame,
    chip_df: pd.DataFrame,
    industry_map: pd.DataFrame,
    periods: int = 12,
) -> pd.DataFrame:
    """
    月 × 產業排名矩陣（輪動歷史）

    Returns:
        DataFrame with index=month, columns=industry, values=rank
    """
    if revenue_df.empty or industry_map.empty:
        return pd.DataFrame()

    revenue_df = revenue_df.copy()
    revenue_df["date"] = pd.to_datetime(revenue_df["date"])
    revenue_df["month"] = revenue_df["date"].dt.to_period("M")

    months = sorted(revenue_df["month"].unique())[-periods:]

    results = {}
    for month in months:
        month_rev = revenue_df[revenue_df["month"] == month]
        momentum = calc_industry_momentum(month_rev, industry_map, lookback_months=1)
        if not momentum.empty:
            rank_dict = dict(zip(momentum["industry"], momentum["rank"]))
            results[str(month)] = rank_dict

    if not results:
        return pd.DataFrame()

    return pd.DataFrame(results).T
