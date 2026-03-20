# 趨勢過濾MA（TrendFilteredMAStrategy）

> 類型：技術面 ｜ 檔案：`analysis/strategies/trend_filtered_ma.py`

## 核心邏輯

在 MA200 確認多頭趨勢的前提下，使用短期均線交叉搭配回檔反彈進場。

## 參數說明

| 參數 | 預設值 | 型別 | 說明 |
|------|--------|------|------|
| `fast_period` | 10 | int | 快速均線週期 |
| `slow_period` | 40 | int | 慢速均線週期 |
| `trend_period` | 200 | int | 趨勢判定均線週期 |
| `min_holding_days` | 15 | int | 最低持有天數 |
| `atr_period` | 14 | int | ATR 計算週期 |
| `atr_threshold` | 0.8 | float | ATR 百分比閾值（%） |
| `use_trend_filter` | True | bool | 是否啟用趨勢過濾 |
| `use_atr_filter` | True | bool | 是否啟用波動過濾 |
| `trend_exit` | True | bool | 是否啟用跌破趨勢線賣出 |
| `use_pullback_entry` | True | bool | 是否啟用回檔反彈進場 |

### 參數詳解

- **`fast_period`**（快速均線週期）
  - 同 MA 交叉策略的 fast_period，預設 10（原始 5 太短）
  - 建議範圍：5 ~ 20

- **`slow_period`**（慢速均線週期）
  - 同 MA 交叉策略的 slow_period，預設 40（原始 20 太短）
  - 建議範圍：20 ~ 60

- **`trend_period`**（趨勢判定均線週期）
  - 用來判斷大趨勢方向，股價必須在此均線之上才允許做多
  - 200 是經典的長期趨勢線（約 10 個月）
  - 建議範圍：100 ~ 300

- **`trend_exit`**（跌破趨勢線賣出）
  - 獨立於 `use_trend_filter`，即使不啟用趨勢過濾，跌破 MA200×0.98 仍可觸發保護性賣出
  - 不受最低持有期限制，確保止損生效

## 買賣條件

- **買入**：(快線上穿慢線 或 回檔反彈) + 股價 > MA(trend_period) + ATR% > 閾值
- **賣出**：快線下穿慢線（需超過最低持有期）或 跌破 MA(trend_period)×0.98（不受持有期限制）

## 學理基礎

Mebane Faber (2007) *A Quantitative Approach to Tactical Asset Allocation* 提出使用 200 日 MA 作為趨勢過濾器，僅在價格高於 200MA 時做多。結合 MA 交叉與回檔反彈邏輯。

## 參考文獻

| # | 來源 | 說明 | PDF |
|---|------|------|-----|
| 1 | Faber, M. (2007). *A Quantitative Approach to Tactical Asset Allocation*. Journal of Wealth Management. | 200MA 趨勢過濾的學術驗證 | 付費牆 |

## Code Review 修復記錄

| # | 嚴重度 | 問題 | 修復狀態 |
|---|--------|------|---------|
| 11 | MEDIUM | `use_trend=False` 靜默關閉趨勢止損 → 解耦 `trend_exit` 獨立運作 | ✓ 已修復 |
