# 推薦命中率儀表板 — 設計文件

> **狀態**：開發中（本地 SQLite 模式）
> **後續**：切換到 Supabase 真實資料後，刪除此標註

## 目標

為每日選股報告建立績效追蹤儀表板，回答四個問題：
1. 哪些策略推薦的股票後來真的漲了？（策略拆分命中率）
2. 排名靠前的股票是否真的比排名靠後的好？（排名 vs 績效）
3. 整體推薦品質隨時間有沒有在改善？（時間趨勢）
4. 整體勝率和報酬分佈如何？（整體概覽）

## 架構

```
Supabase recommendation_history ─┐
                                 ├──→ seed_recommendation_data.py ──→ data/recommendation_local.db
reports/daily_pick_*.md ─────────┘                                            │
                                                                              ▼
        analysis/utils/recommendation_db.py ←── env RECOMMENDATION_DB_SOURCE
                        │
                        ▼
        analysis/pages/13_推薦追蹤.py （四個區塊）
```

**關鍵設計**：資料層 `recommendation_db.py` 封裝資料來源切換，頁面只呼叫資料層函式。
切換到正式環境只需設環境變數 `RECOMMENDATION_DB_SOURCE=supabase`，不碰頁面程式碼。

## 資料層 — `analysis/utils/recommendation_db.py`

```python
# ⚠️ 開發模式預設 sqlite；正式環境設環境變數 RECOMMENDATION_DB_SOURCE=supabase
_DATA_SOURCE = os.getenv("RECOMMENDATION_DB_SOURCE", "sqlite")
_SQLITE_PATH = PROJECT_ROOT / "data" / "recommendation_local.db"
```

提供的函式（全部回傳 DataFrame）：

| 函式 | 用途 |
|------|------|
| `load_all_recommendations()` | 全量推薦記錄（JSONB 欄位自動轉 dict） |
| `load_recommendations_by_date(start, end)` | 日期範圍過濾 |
| `load_performance_summary()` | 整體績效摘要（平均報酬、勝率、樣本數） |
| `load_strategy_breakdown()` | 展開 strategy_votes → 每策略推薦次數 + 勝率 |
| `load_version_timeline()` | git_commit + app_version 的日期序列（版本變更點） |

**JSONB 型別處理**：SQLite 儲存 JSONB 為 TEXT，讀出後自動 `json.loads()` 轉換。
Supabase 透過 SQLAlchemy 讀出已是 dict，無需轉換。資料層統一處理此差異，
頁面拿到的一律是 dict。

```python
_JSONB_COLUMNS = ["strategy_votes", "strategy_hashes", "strategy_weights", "picker_config"]

def _normalize_jsonb(df: pd.DataFrame) -> pd.DataFrame:
    """SQLite 讀出的 JSONB 欄位為 TEXT，轉為 dict"""
    for col in _JSONB_COLUMNS:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: json.loads(x) if isinstance(x, str) else x)
    return df
```

## 種子資料腳本 — `scripts/seed_recommendation_data.py`

**三層策略**（優先順序）：

1. **優先：從 Supabase `recommendation_history` 直接 dump**（如有資料）→ 完整 JSONB、git_commit、所有欄位
2. **Fallback：從 Markdown 解析** → stock_id、stock_name、rank、total_score、entry_price、report_date 可精確解析；strategy_votes 降級重建（只有 strategy_name + recent_score，缺 latest_signal）；git_commit 為 7 位縮寫
3. **離線模式（`--mock-only`）**：純模擬資料，不需要任何外部連線

**後續價格取得**：
- 有 Supabase 連線 → 從 `daily_price` 查 T+5/T+10/T+20 交易日收盤價
- 無連線 → 使用 bootstrap sampling 從真實報酬率分佈抽樣（如有真實資料），否則用 N(0.5%, 3%) 常態分佈

**模擬資料生成**：
- 基於真實資料的 bootstrap sampling（從已有記錄隨機抽取 report_date + return 組合）
- 模擬記錄標記 `is_simulated = True`
- 報酬率限制在 [-15%, +15%] 範圍內避免離群值
- 預設補到 30 天，可用 `--days N` 調整

**Schema**：與 Supabase `recommendation_history` 一致，額外加 `is_simulated BOOLEAN DEFAULT FALSE`。
JSONB 欄位以 JSON TEXT 儲存（SQLite 不支援原生 JSONB）。

CLI：
```bash
uv run python scripts/seed_recommendation_data.py              # 自動選最佳來源 + 補模擬到 30 天
uv run python scripts/seed_recommendation_data.py --real-only  # 只用真實資料，不補模擬
uv run python scripts/seed_recommendation_data.py --mock-only  # 純模擬，不需外部連線
uv run python scripts/seed_recommendation_data.py --days 60    # 補模擬到 60 天
```

## 儀表板頁面 — `analysis/pages/13_推薦追蹤.py`

### Sidebar 全域篩選
- 日期範圍（`st.date_input`）
- 排名範圍（如只看 Top 10）
- 是否排除模擬資料

### 區塊 1：整體績效概覽
- 頂部 metrics row（`st.metric`）：T+5/T+10/T+20 平均報酬 + 勝率、累計推薦筆數、追蹤天數
- 報酬分佈直方圖（T+5/T+10/T+20 三條疊加）

### 區塊 2：策略拆分命中率
- 表格：策略名、推薦次數、T+5 勝率、T+5 平均報酬、T+10 勝率、T+10 平均報酬
- 長條圖：按 T+5 勝率排序
- 資料來自 `load_strategy_breakdown()`，展開 strategy_votes JSONB

### 區塊 3：排名 vs 績效
- 散點圖：X = 推薦排名，Y = T+5 報酬率，加趨勢線和 r²
- 分組長條圖：Top 5 / Top 6-10 / Top 11-20 平均報酬對比

### 區塊 4：時間趨勢
- 折線圖：X = 報告日期，Y = 當日推薦平均 T+5 報酬
- 滾動 5 日均線平滑波動
- 標記版本變更點（從 `load_version_timeline()` 取得 git_commit 變動日期）

## 測試

| 測試檔案 | 覆蓋範圍 |
|---------|---------|
| `tests/test_recommendation_db.py` | 資料層：SQLite 讀取、JSONB TEXT→dict 轉換、Supabase 切換、空資料處理、strategy_breakdown 展開 |
| `tests/test_seed_recommendation.py` | 種子腳本：Supabase dump、Markdown 解析 regex、模擬資料生成（範圍檢查）、SQLite 寫入 |

## 檔案清單

| 檔案 | 動作 |
|------|------|
| `analysis/utils/recommendation_db.py` | 新增 — 資料層（含 JSONB 轉換） |
| `analysis/pages/13_推薦追蹤.py` | 新增 — 儀表板頁面 |
| `scripts/seed_recommendation_data.py` | 新增 — 種子資料腳本（三層策略） |
| `tests/test_recommendation_db.py` | 新增 — 資料層測試 |
| `tests/test_seed_recommendation.py` | 新增 — 種子腳本測試 |
| `.gitignore` | 修改 — 加入 `data/recommendation_local.db` |
| `CLAUDE.md` | 修改 — 頁面清單（12→13）、測試清單、Scripts 表格 |
| `analysis/documents/測試說明.md` | 修改 — 加入新測試檔案 |
| `CHANGELOG.md` | 修改 |

## 切換到正式環境

1. 設環境變數 `RECOMMENDATION_DB_SOURCE=supabase`（Cloud Run YAML 或 `.env`）
2. 刪除或保留 SQLite 檔（不影響功能）
