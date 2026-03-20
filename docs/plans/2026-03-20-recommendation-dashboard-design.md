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
reports/daily_pick_*.md ──→ seed_recommendation_data.py ──→ data/recommendation_local.db
                                                                       │
                                                                       ▼
analysis/utils/recommendation_db.py ←── _DATA_SOURCE = "sqlite" | "supabase"
                │
                ▼
analysis/pages/13_推薦追蹤.py （四個區塊）
```

**關鍵設計**：資料層 `recommendation_db.py` 封裝資料來源切換，頁面只呼叫資料層函式。
切換到正式環境只需改 `_DATA_SOURCE = "supabase"`，不碰頁面程式碼。

## 資料層 — `analysis/utils/recommendation_db.py`

```python
_DATA_SOURCE = "sqlite"  # ⚠️ 開發模式：切換到正式環境改為 "supabase"
_SQLITE_PATH = PROJECT_ROOT / "data" / "recommendation_local.db"
```

提供的函式（全部回傳 DataFrame）：

| 函式 | 用途 |
|------|------|
| `load_all_recommendations()` | 全量推薦記錄 |
| `load_recommendations_by_date(start, end)` | 日期範圍過濾 |
| `load_performance_summary()` | 整體績效摘要（平均報酬、勝率、樣本數） |

SQLite 和 Supabase 的 schema 完全一致（`recommendation_history` 表），SQL 查詢共用。

## 種子資料腳本 — `scripts/seed_recommendation_data.py`

流程：
1. 掃描 `reports/daily_pick_*.md`，用 regex 解析推薦股票的 stock_id、stock_name、rank、total_score、agree_count、entry_price、report_date
2. 從 Supabase `daily_price` 查後續真實價格（唯讀），計算 T+5/T+10/T+20 報酬率
3. 如果真實資料不足目標天數，以真實資料的統計分佈為基礎生成模擬記錄（標記 `is_simulated = True`）
4. 寫入 `data/recommendation_local.db`

Schema 與 Supabase `recommendation_history` 一致，額外加 `is_simulated BOOLEAN DEFAULT FALSE`。

CLI：
```bash
uv run python scripts/seed_recommendation_data.py              # 解析真實 + 補模擬到 30 天
uv run python scripts/seed_recommendation_data.py --real-only  # 只用真實資料
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
- 從 `strategy_votes` JSONB 解析，統計每個策略「投正分 → 後續表現」

### 區塊 3：排名 vs 績效
- 散點圖：X = 推薦排名，Y = T+5 報酬率，加趨勢線和 r²
- 分組長條圖：Top 5 / Top 6-10 / Top 11-20 平均報酬對比

### 區塊 4：時間趨勢
- 折線圖：X = 報告日期，Y = 當日推薦平均 T+5 報酬
- 滾動 5 日均線平滑波動
- 標記版本變更點（git commit 變動日期）

## 測試

| 測試檔案 | 覆蓋範圍 |
|---------|---------|
| `tests/test_recommendation_db.py` | 資料層：SQLite 讀取、Supabase 切換、空資料處理 |
| `tests/test_seed_recommendation.py` | 種子腳本：報告解析 regex、模擬資料生成、SQLite 寫入 |

## 檔案清單

| 檔案 | 動作 |
|------|------|
| `analysis/utils/recommendation_db.py` | 新增 — 資料層 |
| `analysis/pages/13_推薦追蹤.py` | 新增 — 儀表板頁面 |
| `scripts/seed_recommendation_data.py` | 新增 — 種子資料腳本 |
| `tests/test_recommendation_db.py` | 新增 — 資料層測試 |
| `tests/test_seed_recommendation.py` | 新增 — 種子腳本測試 |
| `.gitignore` | 修改 — 加入 `data/recommendation_local.db` |
| `CLAUDE.md` | 修改 — 頁面清單、測試清單 |
| `CHANGELOG.md` | 修改 |

## 切換到正式環境

1. `recommendation_db.py` 中 `_DATA_SOURCE = "supabase"`
2. 刪除或保留 SQLite 檔（不影響功能）
