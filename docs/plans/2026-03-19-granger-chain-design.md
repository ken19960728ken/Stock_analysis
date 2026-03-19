# Phase 3.5b：數據驅動供應鏈發現 — 設計文件

## 目標

從「人工定義供應鏈」進化為「數據驅動發現」，使用 Granger 因果檢定自動偵測次產業間的營收連動關係，捕捉現有 13 條手動供應鏈未覆蓋的產業連動。

## 學理依據

Granger 因果檢定（Granger, 1969）：若時間序列 X 的歷史值能顯著提升對 Y 的預測能力（F-test），則 X「Granger-causes」Y。應用於產業營收 YoY 序列，可推導上游營收變化是否領先下游。

## 架構

### 方案：獨立模組 + Tab 4 整合

新增 `analysis/utils/granger_chain.py` 模組，與現有 `supply_chain.py`（手動定義）共存。UI 在 Tab 4 加 radio 切換「手動定義 / 自動發現」。

**資料流**：

```
month_revenue (DB) → 按次產業聚合月度 YoY → 58 條時間序列
  → 兩兩 Granger 因果檢定 (statsmodels)
  → 過濾 p < threshold 的有效 pair
  → 建構有向圖 (networkx DiGraph)
  → 拓撲排序推導上下游順序
  → 快取結果至本地 JSON (data_cache/)
```

### 核心函數

| 函數 | 輸入 | 輸出 | 說明 |
|------|------|------|------|
| `build_industry_series()` | revenue_df, industry_map | Dict[str, pd.Series] | 58 個次產業的月度 YoY 時間序列 |
| `granger_pairwise()` | series_dict, max_lag=3, p_threshold=0.05 | DataFrame[source, target, lag, f_stat, p_value] | 全配對 Granger 檢定，回傳顯著的因果 pair |
| `build_causal_graph()` | pairs_df | nx.DiGraph | 建構因果有向圖 |
| `discover_chains()` | graph | List[List[str]] | 從 DAG 中提取最長路徑作為「自動發現的供應鏈」 |
| `load_or_compute()` | revenue_df, industry_map, cache_path | (pairs_df, graph) | 快取層：JSON 存在且未過期就讀取，否則重算 |

### Granger 檢定細節

- 58 個次產業 → 3,306 個 pair × max_lag 個 lag
- 使用 `statsmodels.tsa.stattools.grangercausalitytests`
- 每個 pair 取所有 lag 中最顯著的（最小 p-value）
- 時間序列長度 < max_lag + 3 的 pair 跳過
- 預估計算時間：5-15 秒

### 快取設計

- 路徑：`data_cache/granger_results.json`（`data_cache/` 已在 `.gitignore`）
- 快取鍵：包含 `max_lag`、`p_threshold`、資料日期範圍
- 過期：檔案修改時間超過 7 天自動重算
- 格式：JSON（pairs list + metadata）

### 視覺化

- **技術**：Plotly scatter + networkx spring layout
- **節點**：次產業，大小 = 因果連結數（degree），顏色按 sector 分群
- **邊**：有向箭頭，寬度 = F-stat，hover 顯示 p-value / lag / F-stat
- **互動**：Plotly 原生 hover + zoom + pan

## UI 設計

### Tab 4 改造

```
Tab 4: 🔗 供應鏈分析
├── radio: 「手動定義」 / 「自動發現」
│
├── [手動定義] ← 原有邏輯不變
│   ├── selectbox 選擇 13 條供應鏈
│   ├── 各環節營收動能 bar chart
│   └── 領先落後矩陣 heatmap
│
└── [自動發現]
    ├── Sidebar: max_lag (1-6, 預設 3), p_threshold (0.01/0.05/0.10)
    ├── 按鈕「執行 Granger 檢定」
    ├── 因果網絡圖（Plotly + networkx）
    ├── 顯著因果關係表格（source → target, lag, F-stat, p-value）
    └── 自動發現的供應鏈列表（拓撲排序結果）
```

## 修改檔案

| # | 檔案 | 動作 | 說明 |
|---|------|------|------|
| 1 | `analysis/utils/granger_chain.py` | 新增 | 核心模組（Granger 檢定 + DAG + 快取） |
| 2 | `analysis/pages/9_產業輪動.py` | 修改 | Tab 4 加 radio 切換 + 自動發現 UI |
| 3 | `tests/test_granger_chain.py` | 新增 | 7 個測試 |
| 4 | `analysis/documents/9_產業輪動/產業輪動模型.md` | 修改 | 新增 Granger 因果 Section |
| 5 | `README.md` | 修改 | 供應鏈描述加入自動發現 |
| 6 | `CLAUDE.md` | 修改 | 新增模組描述 |

## 測試計劃

| 測試 | 說明 |
|------|------|
| `test_build_industry_series` | 時間序列聚合正確 |
| `test_granger_pairwise_basic` | 構造因果假資料，驗證檢測到 |
| `test_granger_pairwise_no_signal` | 獨立噪音，不應產生顯著結果 |
| `test_granger_pairwise_insufficient_data` | 資料不足應回傳空 |
| `test_build_causal_graph` | DiGraph 節點/邊正確 |
| `test_discover_chains` | DAG 拓撲排序正確 |
| `test_load_or_compute_cache` | 快取寫入/讀取/過期 |

## 向後相容

- Tab 4 預設「手動定義」，原有 13 條供應鏈邏輯完全不動
- `supply_chain.py` 不修改
- 自動發現為可選功能，不影響現有使用者

## 技術依賴

- `statsmodels 0.14.6`（已安裝）— `grangercausalitytests`
- `networkx`（**未安裝**，需加入 `pyproject.toml` 的 `analysis` extra）
- `plotly`（已有）
