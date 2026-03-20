# 量價動能（VolumePriceMomentumStrategy）

> 類型：技術面 ｜ 檔案：`analysis/strategies/volume_price_momentum.py`

## 核心邏輯

成交量放大突破搭配 OBV 資金流向確認，判斷量價齊揚的真實突破。

## 參數說明

| 參數 | 預設值 | 型別 | 說明 |
|------|--------|------|------|
| `volume_multiple` | 2.5 | float | 放量倍數 |
| `breakout_period` | 20 | int | 突破回顧期 |
| `obv_lookback` | 5 | int | OBV 斜率計算期 |
| `trend_period` | 60 | int | 趨勢均線期數 |
| `exit_ma_period` | 20 | int | 出場均線 |
| `shrink_days` | 5 | int | 量能萎縮天數 |
| `confirm_days` | 2 | int | 突破確認天數 |

### 參數詳解

- **`volume_multiple`**（放量倍數）
  - 成交量需超過 20 日均量的倍數才視為「放量」
  - 2.5 → 較嚴格，減少假突破（原始 2.0 太鬆）
  - 建議範圍：1.5 ~ 4.0

- **`breakout_period`**（突破回顧期）
  - 用前 N 日最高收盤價作為突破基準
  - 建議範圍：10 ~ 40

- **`confirm_days`**（突破確認天數）
  - 連續 N 日收在前高之上才確認突破
  - 2 → 需連續 2 日站穩，避免假突破
  - 建議範圍：1 ~ 5

- **`shrink_days`**（量能萎縮天數）
  - 連續 N 日量低於均量，**搭配跌破突破價**才觸發賣出
  - 5 → 約一週（原始 3 太短，健康縮量整理期也觸發）
  - 建議範圍：3 ~ 10

## 買賣條件

- **買入**：連續站穩前高 + 近期放量 + OBV 正斜率 + 股價 > 趨勢均線
- **賣出**：跌破 exit_ma 或（量縮 N 日 + 跌破突破價）

## 學理基礎

量價關係是技術分析的基石。Joseph Granville (1963) *New Key to Stock Market Profits* 提出 OBV（On-Balance Volume），透過成交量的累積方向判斷資金流向。Jegadeesh & Titman (1993) *Returns to Buying Winners and Selling Losers* 驗證了價格動量效應。

## 參考文獻

| # | 來源 | 說明 | PDF |
|---|------|------|-----|
| 1 | Granville, J.E. (1963). *New Key to Stock Market Profits*. Prentice Hall. | OBV 原創著作 | — (書籍) |
| 2 | Jegadeesh, N. & Titman, S. (1993). *Returns to Buying Winners and Selling Losers*. Journal of Finance, 48(1). | 動量效應的經典實證 | 付費牆 |

## Code Review 修復記錄

| # | 嚴重度 | 問題 | 修復狀態 |
|---|--------|------|---------|
| 12 | MEDIUM | 健康縮量整理期也觸發賣出 → 量縮賣出需搭配跌破突破價 | ✓ 已修復 |
