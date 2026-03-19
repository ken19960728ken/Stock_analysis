"""
Granger 因果供應鏈自動發現 — 數據驅動的產業連動分析

使用 Granger 因果檢定自動偵測次產業間的營收連動關係，
建構因果有向圖（DAG），推導上下游順序。
"""

import hashlib
import json
import time
from pathlib import Path

import networkx as nx
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


def build_causal_graph(pairs_df: pd.DataFrame) -> nx.DiGraph:
    """從顯著因果 pair 建構有向圖

    Args:
        pairs_df: granger_pairwise() 的回傳值

    Returns:
        nx.DiGraph，邊屬性含 lag, f_stat, p_value
    """
    G = nx.DiGraph()
    if pairs_df.empty:
        return G

    for _, row in pairs_df.iterrows():
        G.add_edge(
            row["source"], row["target"],
            lag=row["lag"],
            f_stat=row["f_stat"],
            p_value=row["p_value"],
        )
    return G


def discover_chains(graph: nx.DiGraph, min_length: int = 3) -> list[list[str]]:
    """從因果 DAG 中提取最長路徑作為「自動發現的供應鏈」

    Args:
        graph: 因果有向圖
        min_length: 最短鏈長度（節點數）

    Returns:
        按長度降冪排序的鏈列表
    """
    if len(graph.nodes) == 0:
        return []

    # 移除環（保留 F-stat 較大的邊）以得到 DAG
    dag = graph.copy()
    while not nx.is_directed_acyclic_graph(dag):
        try:
            cycle = nx.find_cycle(dag)
        except nx.NetworkXNoCycle:
            break
        # 移除環中 F-stat 最小的邊
        weakest = min(cycle, key=lambda e: dag.edges[e[0], e[1]].get("f_stat", 0))
        dag.remove_edge(weakest[0], weakest[1])

    # 從每個源節點（入度=0）出發，找最長路徑
    chains = []
    sources = [n for n in dag.nodes if dag.in_degree(n) == 0]

    for source in sources:
        for target in dag.nodes:
            if source == target:
                continue
            for path in nx.all_simple_paths(dag, source, target):
                if len(path) >= min_length:
                    chains.append(path)

    # 去重（子路徑被更長路徑包含時移除）
    chains.sort(key=len, reverse=True)
    unique_chains = []
    for chain in chains:
        chain_set = set(tuple(chain))
        is_subset = False
        for existing in unique_chains:
            if chain_set.issubset(set(tuple(existing))):
                is_subset = True
                break
        if not is_subset:
            unique_chains.append(chain)

    return unique_chains


_CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 天


def load_or_compute(
    revenue_df: pd.DataFrame,
    industry_map: pd.DataFrame,
    cache_path: str = "data_cache/granger_results.json",
    max_lag: int = 3,
    p_threshold: float = 0.05,
    ttl: int = _CACHE_TTL_SECONDS,
) -> tuple[pd.DataFrame, nx.DiGraph]:
    """計算 Granger 因果關係，支援本地 JSON 快取

    Args:
        cache_path: 快取檔案路徑
        ttl: 快取有效秒數（預設 7 天）

    Returns:
        (pairs_df, causal_graph)
    """
    cache_file = Path(cache_path)
    cache_key = f"{max_lag}_{p_threshold}"

    # 嘗試讀取快取
    if cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < ttl:
            try:
                with open(cache_file) as f:
                    cached = json.load(f)
                if cached.get("cache_key") == cache_key:
                    pairs = pd.DataFrame(cached["pairs"])
                    graph = build_causal_graph(pairs)
                    return pairs, graph
            except (json.JSONDecodeError, KeyError):
                pass

    # 計算
    series = build_industry_series(revenue_df, industry_map)
    pairs = granger_pairwise(series, max_lag=max_lag, p_threshold=p_threshold)
    graph = build_causal_graph(pairs)

    # 寫入快取
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_data = {
        "cache_key": cache_key,
        "computed_at": time.time(),
        "pairs": pairs.to_dict(orient="records") if not pairs.empty else [],
    }
    with open(cache_file, "w") as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)

    return pairs, graph
