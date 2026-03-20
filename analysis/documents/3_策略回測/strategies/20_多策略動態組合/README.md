# 多策略動態組合（AdaptiveEnsembleStrategy）

> 類型：技術面+籌碼面+基本面 動態加權 ｜ 檔案：`analysis/strategies/adaptive_ensemble.py`

## 核心邏輯

同時執行三個子策略維度（法人跟單 + 價值投資 + 趨勢動能），以固定權重加權合成分數，並要求至少 N 個子策略同意（共識機制）才觸發訊號。

## 參數說明

| 參數 | 預設值 | 型別 | 說明 |
|------|--------|------|------|
| `institutional_weight` | 0.40 | float | 法人跟單子策略權重 |
| `value_weight` | 0.30 | float | 價值投資子策略權重 |
| `trend_weight` | 0.30 | float | 趨勢動能子策略權重 |
| `buy_threshold` | 0.4 | float | 加權分數買入門檻 |
| `sell_threshold` | -0.3 | float | 加權分數賣出門檻 |
| `min_agree` | 2 | int | 至少 N 個子策略同意 |
| `inst_consecutive_days` | 3 | int | 法人連續買超天數 |
| `pe_threshold` | 20 | int | PE 低估門檻 |
| `dividend_yield_min` | 2.0 | float | 殖利率下限（%） |
| `trend_period` | 60 | int | 趨勢判斷均線期數 |
| `fast_period` | 10 | int | 趨勢動能快線 |
| `slow_period` | 30 | int | 趨勢動能慢線 |
| `min_holding_days` | 20 | int | 最低持有天數 |

### 參數詳解

- **`institutional_weight`**（法人權重）：預設 40%（回測 Sharpe 最高），建議 0.2~0.6

- **`min_agree`**（共識門檻）
  - 三個子策略中至少 N 個同時看多才買入
  - 2 → 至少 2/3 同意；3 → 全部同意（最嚴格）

- **`inst_consecutive_days`**（法人連續買超天數）：建議 2~7

- **`pe_threshold`** / **`dividend_yield_min`**
  - 價值投資子策略的 PE 上限和殖利率下限
  - PE < 門檻 → 加分；PE > 30 → 扣分

- **`min_holding_days`**（最低持有天數）
  - 20 → 約一個月，避免頻繁進出

### 三維度子策略

1. **法人跟單**：連續 N 日買超 → +1 分，連續 N 日賣超 → -1 分
2. **價值投資**：低 PE + 高殖利率 + 營收成長 → 加分
3. **趨勢動能**：快線上穿慢線 + 股價 > 趨勢均線 → +1 分

## 買賣條件

- **買入**：加權總分 > buy_threshold 且 ≥ min_agree 個子策略看多
- **賣出**：加權總分 < sell_threshold 且 ≥ min_agree 個子策略看空（需超過最低持有期）

## 學理基礎

Breiman (1996) *Bagging Predictors* 提出 Ensemble 方法（集成學習），透過組合多個弱學習器提升預測穩定性。DeMiguel, Garlappi & Uppal (2009) *Optimal Versus Naive Diversification* 發現等權重組合在實務上常優於最佳化組合。

## 參考文獻

| # | 來源 | 說明 | PDF |
|---|------|------|-----|
| 1 | Breiman, L. (1996). *Bagging Predictors*. Machine Learning, 24(2). | 集成方法 | [PDF](breiman-1996-bagging.pdf) |
| 2 | DeMiguel, V., Garlappi, L. & Uppal, R. (2009). *Optimal Versus Naive Diversification*. Review of Financial Studies, 22(5). | 等權重 vs 最佳化組合 | 付費牆 |

## Code Review 修復記錄

| # | 嚴重度 | 問題 | 修復狀態 |
|---|--------|------|---------|
| 9 | **HIGH** | 法人欄位偵測 `"buy"` 誤中單邊買量 → 優先找含 `"net"` 的淨買超欄位 | ✓ 已修復 |
