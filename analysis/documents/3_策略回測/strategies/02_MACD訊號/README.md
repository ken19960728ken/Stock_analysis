# MACD 訊號（MACDStrategy）

> 類型：技術面 ｜ 檔案：`analysis/strategies/macd_signal.py`

## 核心邏輯

MACD Histogram 連續確認 + MA 趨勢過濾 + Price/MACD 背離偵測。Histogram 連續 N 根正值且股價在趨勢均線上方時買入，連續 N 根負值時賣出。支援多空背離增強訊號。

## 參數說明

| 參數 | 預設值 | 型別 | 說明 |
|------|--------|------|------|
| `fast` | 12 | int | 快線 EMA 週期 |
| `slow` | 26 | int | 慢線 EMA 週期 |
| `signal` | 9 | int | 訊號線 EMA 週期 |
| `confirm_bars` | 2 | int | Histogram 連續確認根數 |
| `trend_period` | 100 | int | 趨勢過濾均線週期（SMA） |
| `use_divergence` | True | bool | 是否啟用背離偵測 |
| `divergence_lookback` | 30 | int | 背離回溯期 |
| `divergence_order` | 5 | int | 局部極值計算階數 |

### 參數詳解

- **`fast`**（快線 EMA 週期）
  - 計算 MACD Line 的短期 EMA
  - 12 是 Gerald Appel 原始設計值，約 2.5 週
  - 縮小會讓 MACD 更靈敏，放大會讓 MACD 更平滑
  - 建議範圍：8 ~ 20

- **`slow`**（慢線 EMA 週期）
  - 計算 MACD Line 的長期 EMA
  - 26 是原始設計值，約 5 週
  - 建議範圍：20 ~ 40
  - **必須大於 `fast`**

- **`signal`**（訊號線 EMA 週期）
  - 對 MACD Line 再做一次 EMA 平滑
  - 9 是原始設計值
  - 越小越靈敏但假訊號多，越大越遲鈍但訊號可靠
  - 建議範圍：5 ~ 15

- **`confirm_bars`**（連續確認根數）
  - Histogram 需連續 N 根同方向才確認訊號
  - 2 → 連續 2 根正值才買入，減少假訊號
  - 建議範圍：1 ~ 5

- **`trend_period`**（趨勢過濾均線週期）
  - 股價需在 SMA(trend_period) 上方才允許買入（做多過濾）
  - 100 → 約 5 個月趨勢線
  - 建議範圍：50 ~ 200

- **`use_divergence`**（是否啟用背離偵測）
  - True → 偵測 Price vs MACD Histogram 的多空背離
  - 多頭背離：價格創新低但 MACD 未創新低 → 加強買入訊號
  - 空頭背離：價格創新高但 MACD 未創新高 → 加強賣出訊號

- **`divergence_lookback`**（背離回溯期）
  - 在最近 N 根 K 棒中尋找背離
  - 建議範圍：20 ~ 60

- **`divergence_order`**（局部極值階數）
  - 用於偵測局部高低點的 `argrelextrema` 階數
  - 建議範圍：3 ~ 10

### MACD 計算公式

```
MACD Line = EMA(fast) - EMA(slow)
Signal Line = EMA(MACD Line, signal)
Histogram = MACD Line - Signal Line
```

## 買賣條件

- **買入**：Histogram 連續 confirm_bars 根 > 0 + 股價 > SMA(trend_period)（+ 可選多頭背離）
- **賣出**：Histogram 連續 confirm_bars 根 < 0（+ 可選空頭背離）

## 學理基礎

Gerald Appel 於 1979 年發明 MACD（Moving Average Convergence Divergence），本質上是雙 EMA 差值的二階動量指標。Appel (2005) *Technical Analysis: Power Tools for Active Investors* 為完整參考書。

## 參考文獻

| # | 來源 | 說明 | PDF |
|---|------|------|-----|
| 1 | Appel, G. (2005). *Technical Analysis: Power Tools for Active Investors*. Financial Times Prentice Hall. | MACD 原創者的完整著作 | — (書籍) |

## Code Review 修復記錄

| # | 嚴重度 | 問題 | 修復狀態 |
|---|--------|------|---------|
| 6 | **HIGH** | 背離偵測邏輯錯誤：應比較「價格兩低點」對應的 MACD_hist 值，而非 MACD 自己的極值 | ✓ 已修復 |
