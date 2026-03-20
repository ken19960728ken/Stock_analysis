# 財報三率（FundamentalRatioStrategy）

> 類型：基本面 ｜ 檔案：`analysis/strategies/fundamental_ratio.py`

## 核心邏輯

計算毛利率、營業利益率、淨利率，當達標條件數 >= min_conditions 時買入。

## 參數說明

| 參數 | 預設值 | 型別 | 說明 |
|------|--------|------|------|
| `gross_margin_threshold` | 25.0 | float | 毛利率門檻（%） |
| `operating_margin_threshold` | 10.0 | float | 營業利益率門檻（%） |
| `net_margin_threshold` | 8.0 | float | 淨利率門檻（%） |
| `min_conditions` | 2 | int | 最少需達標條件數 |

### 參數詳解

- **`gross_margin_threshold`**（毛利率門檻）
  - 毛利率 = (營收 - 成本) / 營收 × 100%
  - 25% 表示產品有基本的獲利能力
  - 建議範圍：15.0 ~ 50.0
  - 產業差異大：IC 設計 40~60%、傳產 10~25%、零售 5~15%

- **`operating_margin_threshold`**（營業利益率門檻）
  - 營業利益率 = 營業利益 / 營收 × 100%
  - 10% 表示本業經營有效率
  - 建議範圍：5.0 ~ 30.0

- **`net_margin_threshold`**（淨利率門檻）
  - 淨利率 = 稅後淨利 / 營收 × 100%
  - 8% 是整體獲利能力的基本要求
  - 建議範圍：3.0 ~ 25.0

- **`min_conditions`**（最少達標條件數）
  - 三率中至少幾個達標才買入
  - 2 → 寬鬆（2/3）；3 → 嚴格（全部）；1 → 非常寬鬆
  - 建議範圍：1 ~ 3

## 買賣條件

- **買入**：達標條件數 >= min_conditions
- **賣出**：達標條件數不足

## 學理基礎

Piotroski (2000) *Value Investing: The Use of Historical Financial Statement Information* 提出 F-Score（9 個會計指標），證明財務體質好的低估值股票報酬更高。本策略使用毛利率、營益率、稅後淨利率的變動趨勢。

## 參考文獻

| # | 來源 | 說明 | PDF |
|---|------|------|-----|
| 1 | Piotroski, J.D. (2000). *Value Investing: The Use of Historical Financial Statement Information to Separate Winners from Losers*. Journal of Accounting Research, 38. | F-Score 財務體質評分 | 付費牆 |

## Code Review 修復記錄

| # | 嚴重度 | 問題 | 修復狀態 |
|---|--------|------|---------|
| 15 | MEDIUM | 欄位偵測缺 `break` + revenue 可能誤匹配 → 加 `is None` 守衛 + 排除 yoy/month/year | ✓ 已修復 |
