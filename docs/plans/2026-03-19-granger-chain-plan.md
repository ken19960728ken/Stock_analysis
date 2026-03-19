# Phase 3.5b：數據驅動供應鏈發現 — 實作計劃

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 使用 Granger 因果檢定自動偵測次產業間的營收連動關係，在 Tab 4 新增「自動發現」模式，與手動定義的 13 條供應鏈共存。

**Architecture:** 新增獨立模組 `analysis/utils/granger_chain.py`，包含 Granger 全配對檢定、DAG 建構、拓撲排序、JSON 快取。UI 在 Tab 4 加 radio 切換手動/自動。視覺化用 Plotly + networkx。

**Tech Stack:** statsmodels（grangercausalitytests）、networkx（DiGraph + spring_layout）、Plotly（scatter + annotations）

---

### Task 1: 安裝 networkx 依賴

**Files:**
- Modify: `pyproject.toml:30-33`

**Step 1: 加入 networkx 到 analysis extra**

在 `pyproject.toml` 第 30-33 行的 `analysis` optional-dependencies 中新增 `networkx`：

```toml
analysis = [
    "streamlit>=1.30.0",
    "fredapi>=0.5.0",
    "networkx>=3.0",
]
```

**Step 2: 安裝依賴**

Run: `uv sync --extra all`
Expected: 成功安裝 networkx

**Step 3: 驗證**

Run: `uv run python -c "import networkx; print(networkx.__version__)"`
Expected: 版本號輸出（如 `3.4.2`）

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: 加入 networkx 依賴（Granger 因果網絡圖）"
```

---

### Task 2: 實作 `granger_chain.py` 核心模組 — build_industry_series + granger_pairwise

**Files:**
- Create: `analysis/utils/granger_chain.py`
- Create: `tests/test_granger_chain.py`

**Step 1: 寫 build_industry_series 的失敗測試**

`tests/test_granger_chain.py`:

```python
"""Granger 因果供應鏈自動發現測試"""

import numpy as np
import pandas as pd
import pytest

from analysis.utils.granger_chain import build_industry_series


@pytest.fixture
def sample_industry_map():
    return pd.DataFrame({
        "stock_id": ["2330", "2317", "2454", "2881", "2882", "2412"],
        "industry_category": ["半導體", "半導體", "半導體", "金融", "金融", "電信"],
        "sector": ["半導體業", "半導體業", "半導體業", "金融業", "金融業", "電信業"],
        "sub_industry": ["IC 設計", "IC 製造", "IC 設計", "銀行", "銀行", "電信"],
    })


@pytest.fixture
def sample_revenue_df():
    """12 個月 × 6 支股票"""
    dates = pd.date_range("2023-01-01", periods=12, freq="MS")
    rows = []
    for d in dates:
        for sid, yoy in [("2330", 15.0), ("2317", 10.0), ("2454", 20.0),
                         ("2881", 5.0), ("2882", 3.0), ("2412", 8.0)]:
            rows.append({
                "stock_id": sid,
                "date": d,
                "revenue": 1e9,
                "month_revenue_year_on_year": yoy + np.random.randn() * 2,
            })
    return pd.DataFrame(rows)


class TestBuildIndustrySeries:
    def test_returns_dict_of_series(self, sample_revenue_df, sample_industry_map):
        result = build_industry_series(sample_revenue_df, sample_industry_map)
        assert isinstance(result, dict)
        assert len(result) > 0
        for key, series in result.items():
            assert isinstance(series, pd.Series)
            assert isinstance(key, str)

    def test_correct_sub_industries(self, sample_revenue_df, sample_industry_map):
        result = build_industry_series(sample_revenue_df, sample_industry_map)
        assert "IC 設計" in result
        assert "IC 製造" in result
        assert "銀行" in result

    def test_empty_input(self, sample_industry_map):
        result = build_industry_series(pd.DataFrame(), sample_industry_map)
        assert result == {}
```

**Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_granger_chain.py::TestBuildIndustrySeries -v`
Expected: FAIL — `ImportError: cannot import name 'build_industry_series'`

**Step 3: 實作 build_industry_series**

建立 `analysis/utils/granger_chain.py`：

```python
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
```

**Step 4: 執行測試確認通過**

Run: `uv run pytest tests/test_granger_chain.py::TestBuildIndustrySeries -v`
Expected: 3 passed

**Step 5: 寫 granger_pairwise 的失敗測試**

在 `tests/test_granger_chain.py` 新增：

```python
from analysis.utils.granger_chain import build_industry_series, granger_pairwise


@pytest.fixture
def causal_series():
    """構造有因果關係的時間序列：A 領先 B 兩期"""
    np.random.seed(42)
    n = 36
    a = np.cumsum(np.random.randn(n))
    b = np.zeros(n)
    b[2:] = a[:-2] + np.random.randn(n - 2) * 0.3  # B 滯後 A 兩期
    months = pd.period_range("2021-01", periods=n, freq="M")
    return {
        "A": pd.Series(a, index=months),
        "B": pd.Series(b, index=months),
    }


class TestGrangerPairwise:
    def test_detects_causal_pair(self, causal_series):
        result = granger_pairwise(causal_series, max_lag=3, p_threshold=0.10)
        assert not result.empty
        assert set(result.columns) >= {"source", "target", "lag", "f_stat", "p_value"}
        # A 應 Granger-cause B
        ab = result[(result["source"] == "A") & (result["target"] == "B")]
        assert not ab.empty

    def test_no_signal_independent_noise(self):
        """獨立噪音序列不應產生顯著因果"""
        np.random.seed(123)
        n = 36
        months = pd.period_range("2021-01", periods=n, freq="M")
        series = {
            "X": pd.Series(np.random.randn(n), index=months),
            "Y": pd.Series(np.random.randn(n), index=months),
        }
        result = granger_pairwise(series, max_lag=3, p_threshold=0.01)
        # 嚴格 p < 0.01 下，獨立噪音很少顯著
        assert len(result) <= 1  # 容許偶發 false positive

    def test_insufficient_data(self):
        """資料不足應回傳空"""
        months = pd.period_range("2021-01", periods=3, freq="M")
        series = {
            "A": pd.Series([1, 2, 3], index=months),
            "B": pd.Series([4, 5, 6], index=months),
        }
        result = granger_pairwise(series, max_lag=3, p_threshold=0.05)
        assert result.empty
```

**Step 6: 執行測試確認失敗**

Run: `uv run pytest tests/test_granger_chain.py::TestGrangerPairwise -v`
Expected: FAIL — `ImportError: cannot import name 'granger_pairwise'`

**Step 7: 實作 granger_pairwise**

在 `analysis/utils/granger_chain.py` 新增：

```python
from statsmodels.tsa.stattools import grangercausalitytests


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
```

**Step 8: 執行測試確認通過**

Run: `uv run pytest tests/test_granger_chain.py -v`
Expected: 6 passed

**Step 9: Commit**

```bash
git add analysis/utils/granger_chain.py tests/test_granger_chain.py
git commit -m "feat: granger_chain 核心模組 — build_industry_series + granger_pairwise"
```

---

### Task 3: 實作 build_causal_graph + discover_chains

**Files:**
- Modify: `analysis/utils/granger_chain.py`
- Modify: `tests/test_granger_chain.py`

**Step 1: 寫失敗測試**

在 `tests/test_granger_chain.py` 新增：

```python
from analysis.utils.granger_chain import (
    build_industry_series,
    granger_pairwise,
    build_causal_graph,
    discover_chains,
)


class TestBuildCausalGraph:
    def test_basic_graph(self):
        pairs_df = pd.DataFrame({
            "source": ["A", "B", "C"],
            "target": ["B", "C", "D"],
            "lag": [1, 2, 1],
            "f_stat": [5.0, 3.0, 4.0],
            "p_value": [0.01, 0.03, 0.02],
        })
        graph = build_causal_graph(pairs_df)
        assert len(graph.nodes) == 4
        assert len(graph.edges) == 3
        assert graph.has_edge("A", "B")

    def test_empty_pairs(self):
        pairs_df = pd.DataFrame(columns=["source", "target", "lag", "f_stat", "p_value"])
        graph = build_causal_graph(pairs_df)
        assert len(graph.nodes) == 0


class TestDiscoverChains:
    def test_linear_chain(self):
        """A→B→C→D 應發現 [A, B, C, D]"""
        pairs_df = pd.DataFrame({
            "source": ["A", "B", "C"],
            "target": ["B", "C", "D"],
            "lag": [1, 1, 1],
            "f_stat": [5.0, 5.0, 5.0],
            "p_value": [0.01, 0.01, 0.01],
        })
        graph = build_causal_graph(pairs_df)
        chains = discover_chains(graph)
        assert len(chains) > 0
        # 最長鏈應包含 4 個節點
        longest = max(chains, key=len)
        assert len(longest) >= 3

    def test_empty_graph(self):
        import networkx as nx
        chains = discover_chains(nx.DiGraph())
        assert chains == []
```

**Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_granger_chain.py::TestBuildCausalGraph tests/test_granger_chain.py::TestDiscoverChains -v`
Expected: FAIL

**Step 3: 實作 build_causal_graph + discover_chains**

在 `analysis/utils/granger_chain.py` 新增：

```python
import networkx as nx


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
        # BFS/DFS 找從 source 出發的所有路徑
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
```

**Step 4: 執行測試確認通過**

Run: `uv run pytest tests/test_granger_chain.py -v`
Expected: 10 passed

**Step 5: Commit**

```bash
git add analysis/utils/granger_chain.py tests/test_granger_chain.py
git commit -m "feat: granger_chain — build_causal_graph + discover_chains（DAG 拓撲排序）"
```

---

### Task 4: 實作快取機制 load_or_compute

**Files:**
- Modify: `analysis/utils/granger_chain.py`
- Modify: `tests/test_granger_chain.py`

**Step 1: 寫失敗測試**

```python
class TestLoadOrCompute:
    def test_computes_and_caches(self, sample_revenue_df, sample_industry_map, tmp_path):
        cache_path = tmp_path / "granger_cache.json"
        pairs, graph = load_or_compute(
            sample_revenue_df, sample_industry_map,
            cache_path=str(cache_path), max_lag=2, p_threshold=0.10,
        )
        assert isinstance(pairs, pd.DataFrame)
        assert cache_path.exists()

    def test_reads_from_cache(self, sample_revenue_df, sample_industry_map, tmp_path):
        cache_path = tmp_path / "granger_cache.json"
        # 第一次計算
        pairs1, _ = load_or_compute(
            sample_revenue_df, sample_industry_map,
            cache_path=str(cache_path), max_lag=2, p_threshold=0.10,
        )
        # 第二次應從快取讀取（比較結果一致）
        pairs2, _ = load_or_compute(
            sample_revenue_df, sample_industry_map,
            cache_path=str(cache_path), max_lag=2, p_threshold=0.10,
        )
        pd.testing.assert_frame_equal(pairs1, pairs2)
```

**Step 2: 執行測試確認失敗**

Run: `uv run pytest tests/test_granger_chain.py::TestLoadOrCompute -v`
Expected: FAIL

**Step 3: 實作 load_or_compute**

```python
_CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 天


def load_or_compute(
    revenue_df: pd.DataFrame,
    industry_map: pd.DataFrame,
    cache_path: str = "data_cache/granger_results.json",
    max_lag: int = 3,
    p_threshold: float = 0.05,
    ttl: int = _CACHE_TTL_SECONDS,
) -> tuple[pd.DataFrame, "nx.DiGraph"]:
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
```

**Step 4: 執行測試確認通過**

Run: `uv run pytest tests/test_granger_chain.py -v`
Expected: 12 passed

**Step 5: Commit**

```bash
git add analysis/utils/granger_chain.py tests/test_granger_chain.py
git commit -m "feat: granger_chain — load_or_compute 快取機制"
```

---

### Task 5: 實作網絡圖視覺化函數

**Files:**
- Modify: `analysis/utils/granger_chain.py`

**Step 1: 實作 plot_causal_network**

```python
def plot_causal_network(
    graph: nx.DiGraph,
    industry_map: pd.DataFrame | None = None,
) -> "go.Figure":
    """用 Plotly + networkx 繪製因果網絡圖

    Args:
        graph: 因果有向圖
        industry_map: 用於按 sector 著色（可選）

    Returns:
        plotly Figure
    """
    import plotly.graph_objects as go

    if len(graph.nodes) == 0:
        fig = go.Figure()
        fig.add_annotation(text="無顯著因果關係", showarrow=False)
        return fig

    # networkx spring layout
    pos = nx.spring_layout(graph, seed=42, k=2.0)

    # sector 顏色映射
    sector_map = {}
    if industry_map is not None and "sub_industry" in industry_map.columns:
        sector_col = "sector" if "sector" in industry_map.columns else "industry_category"
        for _, row in industry_map.drop_duplicates("sub_industry").iterrows():
            if pd.notna(row.get("sub_industry")):
                sector_map[row["sub_industry"]] = row.get(sector_col, "其他")

    sectors = list(set(sector_map.values())) or ["default"]
    color_palette = [
        "#636EFA", "#EF553B", "#00CC96", "#AB63FA", "#FFA15A",
        "#19D3F3", "#FF6692", "#B6E880", "#FF97FF", "#FECB52",
    ]
    sector_colors = {s: color_palette[i % len(color_palette)] for i, s in enumerate(sectors)}

    # 邊
    edge_traces = []
    annotations = []
    for src, tgt, data in graph.edges(data=True):
        x0, y0 = pos[src]
        x1, y1 = pos[tgt]
        f_stat = data.get("f_stat", 1.0)
        p_val = data.get("p_value", 0.05)
        lag = data.get("lag", 1)
        width = max(1, min(5, f_stat / 3))

        edge_traces.append(go.Scatter(
            x=[x0, x1, None], y=[y0, y1, None],
            mode="lines",
            line=dict(width=width, color="rgba(150,150,150,0.5)"),
            hoverinfo="text",
            text=f"{src} → {tgt}<br>lag={lag}, F={f_stat:.2f}, p={p_val:.4f}",
            showlegend=False,
        ))

        # 箭頭
        annotations.append(dict(
            ax=x0, ay=y0, x=x1, y=y1,
            xref="x", yref="y", axref="x", ayref="y",
            showarrow=True, arrowhead=2, arrowsize=1.5,
            arrowwidth=width, arrowcolor="rgba(150,150,150,0.6)",
        ))

    # 節點
    node_x, node_y, node_text, node_size, node_color = [], [], [], [], []
    for node in graph.nodes:
        x, y = pos[node]
        node_x.append(x)
        node_y.append(y)
        degree = graph.degree(node)
        node_text.append(f"{node}<br>degree={degree}")
        node_size.append(max(15, degree * 5))
        sector = sector_map.get(node, "其他")
        node_color.append(sector_colors.get(sector, "#636EFA"))

    node_trace = go.Scatter(
        x=node_x, y=node_y,
        mode="markers+text",
        text=[n for n in graph.nodes],
        textposition="top center",
        textfont=dict(size=10),
        marker=dict(size=node_size, color=node_color, line=dict(width=1, color="white")),
        hovertext=node_text,
        hoverinfo="text",
        showlegend=False,
    )

    fig = go.Figure(data=edge_traces + [node_trace])
    fig.update_layout(
        annotations=annotations,
        template="plotly_dark",
        height=700,
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        margin=dict(l=20, r=20, t=40, b=20),
    )
    return fig
```

**Step 2: 執行全部測試確認不破壞**

Run: `uv run pytest tests/test_granger_chain.py -v`
Expected: 12 passed

**Step 3: Commit**

```bash
git add analysis/utils/granger_chain.py
git commit -m "feat: granger_chain — plot_causal_network 網絡圖視覺化"
```

---

### Task 6: 修改 Tab 4 UI — radio 切換 + 自動發現

**Files:**
- Modify: `analysis/pages/9_產業輪動.py:19-36` (imports)
- Modify: `analysis/pages/9_產業輪動.py:369-439` (Tab 4)

**Step 1: 更新 imports**

在 `9_產業輪動.py` imports 區新增：

```python
from analysis.utils.granger_chain import (
    build_causal_graph,
    discover_chains,
    granger_pairwise,
    build_industry_series,
    load_or_compute,
    plot_causal_network,
)
```

**Step 2: 改造 Tab 4**

將 Tab 4 的內容從原本直接顯示手動供應鏈，改為 radio 切換：

```python
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
        # ... 原有邏輯保持不變 ...

    else:
        # === 自動發現 ===
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
                st.subheader(f"因果網絡圖（{len(graph.nodes)} 個節點，{len(graph.edges)} 條邊）")
                fig_network = plot_causal_network(graph, industry_map)
                st.plotly_chart(fig_network, use_container_width=True)

                # 顯著因果表格
                st.subheader("顯著因果關係")
                display_pairs = pairs.copy()
                display_pairs["p_value"] = display_pairs["p_value"].map(lambda x: f"{x:.4f}")
                display_pairs["f_stat"] = display_pairs["f_stat"].map(lambda x: f"{x:.2f}")
                display_pairs.columns = ["來源（領先）", "目標（落後）", "滯後月數", "F-stat", "p-value"]
                st.dataframe(display_pairs.reset_index(drop=True),
                             use_container_width=True, hide_index=True)

                # 自動發現的供應鏈
                chains = discover_chains(graph)
                if chains:
                    st.subheader("自動發現的供應鏈")
                    for i, chain in enumerate(chains[:10], 1):
                        arrow = " → ".join(chain)
                        st.write(f"**鏈 {i}**（{len(chain)} 環節）：{arrow}")
                else:
                    st.info("未發現長度 ≥ 3 的供應鏈路徑。")
```

**Step 3: 執行全部相關測試**

Run: `uv run pytest tests/test_granger_chain.py tests/test_sector_rotation.py tests/test_supply_chain.py -v`
Expected: 全部通過

**Step 4: Commit**

```bash
git add "analysis/pages/9_產業輪動.py"
git commit -m "feat: Tab 4 新增自動發現模式（Granger 因果網絡圖 + 供應鏈路徑）"
```

---

### Task 7: 更新文件 — 產業輪動模型.md + README.md + CLAUDE.md

**Files:**
- Modify: `analysis/documents/9_產業輪動/產業輪動模型.md`
- Modify: `README.md`
- Modify: `CLAUDE.md`

**Step 1: 更新產業輪動模型.md**

在 Tab 4 的「供應鏈分析」Section 新增「自動發現」子節：

```markdown
### 自動發現（Granger 因果）

**原理**：Granger 因果檢定（1969）— 若時間序列 X 的歷史值能顯著提升對 Y 的預測能力（F-test），
則 X「Granger-causes」Y。對所有次產業 pair 執行檢定，自動偵測營收連動關係。

**操作**：
1. 在 Tab 4 選擇「自動發現（Granger 因果）」
2. 設定最大滯後期數（1-6 月）和顯著性門檻（p < 0.01/0.05/0.10）
3. 點擊「執行 Granger 檢定」

**輸出**：
- 因果網絡圖（節點 = 次產業，邊 = 因果關係，邊寬 = F-stat）
- 顯著因果關係表格（source → target, lag, F-stat, p-value）
- 自動發現的供應鏈列表（DAG 拓撲排序，最長路徑）

**快取**：結果快取至 `data_cache/granger_results.json`，7 天內不重算。
```

**Step 2: 更新 README.md**

產業輪動描述加入「Granger 因果自動發現」：

```
- [x] 產業輪動模型（營收動能 + 法人流向 + 估值面 → 三因子產業排名 + 13 條供應鏈分析 + Granger 因果自動發現 + 指數衰減加權 + ICIR 動態權重）
```

**Step 3: 更新 CLAUDE.md**

新增 `granger_chain.py` 模組描述：

```
| `analysis/utils/granger_chain.py` | Granger 因果供應鏈自動發現（全配對檢定 + DAG + 網絡圖 + 快取） |
```

更新 `9_產業輪動.py` 描述：

```
| `analysis/pages/9_產業輪動.py` | 營收動能 + 法人流向 + 估值面 → 產業排名 + 供應鏈分析 + Granger 因果自動發現 |
```

新增測試表：

```
| `test_granger_chain.py` | Granger 因果供應鏈自動發現測試（12 項） |
```

**Step 4: Commit**

```bash
git add "analysis/documents/9_產業輪動/產業輪動模型.md" README.md CLAUDE.md
git commit -m "docs: 同步 Granger 因果自動發現文件（模型文件 + README + CLAUDE.md）"
```

---

### Task 8: 最終驗證 + 部署

**Step 1: 跑全部相關測試**

Run: `uv run pytest tests/test_granger_chain.py tests/test_sector_rotation.py tests/test_supply_chain.py tests/test_industry_classification.py -v`
Expected: 全部通過

**Step 2: Push**

Run: `git push origin main`

**Step 3: 部署 Analysis Service**

Run: `/deploy analysis`

**Step 4: 本地驗證 UI**

Run: `uv run python main.py --analysis`
進入 9_產業輪動 → Tab 4 → 選「自動發現」→ 執行 Granger 檢定 → 確認網絡圖 + 表格 + 供應鏈列表正確顯示
