# 融資融券訊號（MarginSignalStrategy）

> 類型：籌碼面 ｜ 檔案：`analysis/strategies/margin_signal.py`

## 核心邏輯

融資餘額減少且股價上漲 → 籌碼沉澱（散戶退出、主力介入），產生買入訊號。融資暴增且股價下跌 → 散戶追多被套，產生賣出訊號。

## 參數說明

| 參數 | 預設值 | 型別 | 說明 |
|------|--------|------|------|
| `margin_change_pct` | -10.0 | float | 融資餘額變化門檻（%） |
| `lookback_days` | 10 | int | 回溯天數 |
| `require_price_ma_up` | True | bool | 是否要求 MA20 向上 |
| `use_short_ratio` | False | bool | 是否啟用券資比軋空偵測 |
| `short_ratio_threshold` | 30.0 | float | 券資比門檻（%） |
| `short_ratio_lookback` | 5 | int | 券資比計算回溯天數 |

### 參數詳解

- **`margin_change_pct`**（融資餘額變化門檻）
  - 負值代表融資減少的幅度門檻
  - -5.0 表示融資餘額在回溯期間減少超過 5% 才觸發
  - -3.0 → 更寬鬆；-10.0 → 更嚴格
  - 建議範圍：-15.0 ~ -2.0

- **`lookback_days`**（回溯天數）
  - 比較融資餘額變化的時間窗口
  - 5 天 → 約一週；10 天 → 約兩週
  - 建議範圍：3 ~ 20

- **`short_ratio_lookback`**（券資比計算回溯天數）
  - 計算近 N 日平均券資比，僅在 `use_short_ratio=True` 時生效
  - 建議範圍：3 ~ 10

### 融資欄位偵測順序

1. `MarginPurchaseTodayBalance`、`margin_purchase_balance` 等精確匹配
2. fallback：含 `margin` + `balance`（排除 `short`）的欄位

## 買賣條件

- **買入**：`融資變化 <= margin_change_pct` 且 `股價上漲` 且 `MA20 向上`（+ 可選券資比軋空）
- **賣出**：`融資大幅增加` 且 `股價下跌`

## 學理基礎

Desai et al. (2002) *An Investigation of the Informational Role of Short Interest* 發現融券（Short Interest）包含負面資訊，高融券餘額的股票未來報酬顯著偏低。融資券比（券資比）是台股特有的指標，反映市場多空力道對比。

## 參考文獻

| # | 來源 | 說明 | PDF |
|---|------|------|-----|
| 1 | Desai, H., Ramesh, K., Thiagarajan, S.R. & Balachandran, B.V. (2002). *An Investigation of the Informational Role of Short Interest in the Nasdaq Market*. Journal of Finance, 57(5). | 融券資訊含量的實證研究 | 付費牆 |

## Code Review 修復記錄

| # | 嚴重度 | 問題 | 修復狀態 |
|---|--------|------|---------|
| 13 | MEDIUM | fallback 過於寬鬆可能匹配非餘額欄位 → 精確匹配 + `balance` 過濾 | ✓ 已修復 |
