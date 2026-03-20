# 選股報告追蹤機制 — 設計文件

> 日期：2026-03-20
> 狀態：已確認，待實作

---

## 1. 動機

每日選股報告是系統的最終產出，但目前缺乏兩個關鍵能力：

1. **版本可回溯性**：無法得知一份報告是由哪個版本的策略程式碼、什麼參數、什麼權重產出的。當策略更新後，歷史績效的反饋可能歸因到錯誤的版本。
2. **績效追蹤**：推薦股票後，系統不知道後續表現如何。沒有追蹤的推薦等於沒有反饋的學習。

**原則**：既往不咎，從未來產出的報告開始追蹤。

## 2. 設計決策摘要

| 決策 | 選擇 | 理由 |
|------|------|------|
| 版本追蹤粒度 | Git commit SHA + 策略檔案 SHA256 | 無需手動維護版號，commit 可精確回溯全部程式碼，檔案 hash 可偵測策略變更 |
| 資料儲存 | 單表 + JSONB | 每日最多 20 列，一年 ~5000 列，正規化收益不大 |
| 績效追蹤週期 | T+5 / T+10 / T+20（交易日） | 覆蓋短線到中期策略的預期持有期 |
| T+N 定義 | **交易日**，非日曆日 | 從 daily_price 取推薦日之後第 N 個有交易紀錄的日期 |
| 回填時機 | 每日報告產出時順便回填 | 零額外排程，回填邏輯輕量 |
| 報告分離 | 推薦報告（不可變） + 績效追蹤報告（滾動更新） | 推薦報告產出後不再修改，績效報告是彙總視圖 |

## 3. DB Schema

```sql
CREATE TABLE recommendation_history (
    id               BIGSERIAL PRIMARY KEY,
    report_date      DATE NOT NULL,
    stock_id         VARCHAR(10) NOT NULL,
    stock_name       VARCHAR(50),
    rank             INT,
    total_score      FLOAT,
    agree_count      INT,
    total_strategies INT,
    entry_price      FLOAT,                  -- 推薦日收盤價（T+0 基準）
    rsi              FLOAT,
    week_return      FLOAT,                  -- 推薦時近 5 日漲跌幅 %
    avg_volume_20d   FLOAT,                  -- 20 日均量（張）
    sector           VARCHAR(50),
    sub_industry     VARCHAR(50),

    -- 版本指紋
    git_commit       VARCHAR(40),             -- git rev-parse HEAD
    app_version      VARCHAR(20),             -- pyproject.toml version
    strategy_votes   JSONB,                   -- 各策略投票明細
    strategy_hashes  JSONB,                   -- 各策略檔案 SHA256
    strategy_weights JSONB,                   -- STRATEGY_WEIGHTS 快照
    picker_config    JSONB,                   -- 選股參數快照

    -- 績效追蹤（初始 NULL，回填更新）
    price_t5         FLOAT,
    price_t10        FLOAT,
    price_t20        FLOAT,
    return_t5        FLOAT,                   -- (price_t5 / entry_price - 1) × 100
    return_t10       FLOAT,
    return_t20       FLOAT,

    created_at       TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(report_date, stock_id)
);

CREATE INDEX idx_rec_hist_date ON recommendation_history(report_date);
CREATE INDEX idx_rec_hist_stock ON recommendation_history(stock_id);
```

### JSONB 欄位結構

**strategy_votes**:
```json
{
  "RSI 反轉": {"latest_signal": 1, "recent_score": 3.0, "signal_date": "2026-03-20"},
  "價值投資": {"latest_signal": 0, "recent_score": 1.0, "signal_date": "2026-03-18"}
}
```

**strategy_hashes**:
```json
{
  "rsi_reversal.py": "a1b2c3d4e5f6...",
  "value_investing.py": "f6e5d4c3b2a1...",
  "ma_cross.py": "1a2b3c4d5e6f..."
}
```

**strategy_weights**:
```json
{"RSI 反轉": 1.0, "價值投資": 0.8, "機器學習選股": 0.7}
```

**picker_config**:
```json
{"signal_days": 5, "min_avg_volume": 500, "min_agree": 2, "top_n": 20}
```

## 4. 資料流

```
scan_stocks()                          ← 現有，不改
    ↓
build_report()                         ← 現有，不改（產出 daily_pick_YYYY-MM-DD.md）
    ↓
save_recommendations()                 ← 新增
    ├── collect_version_fingerprint()  ← git SHA + app version
    ├── collect_strategy_hashes()      ← 策略檔案 SHA256
    └── INSERT INTO recommendation_history (return_t* = NULL)
    ↓
backfill_performance()                 ← 新增
    ├── 查詢 return_t5 IS NULL 且有足夠後續交易日的記錄
    ├── 從 daily_price 取第 5/10/20 個交易日的收盤價
    └── UPDATE price_t*, return_t*
    ↓
generate_performance_report()          ← 新增（產出 performance_tracking.md）
```

## 5. 回填邏輯（關鍵：交易日計算）

```python
# 取推薦日之後的交易日序列
SELECT date, close FROM daily_price
WHERE stock_id = :sid AND date > :report_date
ORDER BY date
LIMIT 20

# 用 iloc 取第 N 個交易日
# T+5  = iloc[4]  (index 0-based，第 5 筆)
# T+10 = iloc[9]
# T+20 = iloc[19]

# 判斷是否可回填：
# - T+5:  該股票在推薦日後至少有 5 個交易日資料
# - T+10: 至少 10 個交易日資料
# - T+20: 至少 20 個交易日資料
# 三個窗口獨立判斷，可能 T+5 已回填但 T+20 尚未
```

## 6. 檔案變更清單

| 檔案 | 變更類型 | 說明 |
|------|---------|------|
| `scripts/daily_stock_picker.py` | 修改 | 新增 `save_recommendations()`、`collect_version_fingerprint()`、`collect_strategy_hashes()` |
| `scripts/performance_tracker.py` | **新增** | `backfill_performance()`、`generate_performance_report()`，可獨立執行 |
| `core/db.py` | 修改 | VALID_TABLES 白名單加入 `recommendation_history` |
| `main.py` | 修改 | `run_daily_report()` 串接 save → backfill → performance report |
| `scripts/db_add_constraints.py` | 修改 | 加入 recommendation_history 的 UNIQUE constraint |

## 7. 報告格式

### 每日推薦報告（現有格式 + 版本指紋區塊）

在現有報告末尾新增：

```markdown
## 版本資訊

- **Git Commit**: a1b2c3d
- **App Version**: 1.0.0
- **策略權重**: RSI 反轉(1.0), 價值投資(0.8), ...
- **選股參數**: signal_days=5, min_agree=2, min_volume=500張
```

### 績效追蹤報告（新增，滾動更新）

```markdown
# 選股績效追蹤報告

> 更新日期：2026-03-20
> 追蹤期間：2026-01-01 ~ 2026-03-20

## 整體績效

| 指標 | T+5 | T+10 | T+20 |
|------|-----|------|------|
| 平均報酬 | +1.2% | +2.1% | +3.5% |
| 勝率 | 58% | 55% | 52% |
| 樣本數 | 200 | 180 | 140 |

## 按策略拆分勝率

| 策略 | 推薦次數 | T+5 勝率 | T+10 勝率 | T+20 勝率 |
|------|---------|---------|----------|----------|
| RSI 反轉 | 45 | 62% | 58% | 55% |
| 價值投資 | 38 | 55% | 60% | 63% |

## 最近 5 日推薦追蹤

| 日期 | 股票 | 推薦價 | 現價 | 漲跌幅 | 版本 |
|------|------|-------|------|-------|------|
| 03/18 | 2330 台積電 | 850.0 | 865.0 | +1.8% | a1b2c3d |
```

## 8. 不做的事

- 不回溯歷史報告（既往不咎）
- 不修改現有策略的 generate_signals 介面
- 不影響現有的 `--pick-stocks` 和 `--daily-report` 基本流程（只是在尾部追加步驟）
- 績效追蹤報告不透過 Email 發送（未來可選擇加入）
