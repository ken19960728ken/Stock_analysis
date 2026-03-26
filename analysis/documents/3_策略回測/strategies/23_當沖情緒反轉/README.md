# 23. 當沖情緒反轉（DayTradeSentimentStrategy）

## 策略概述

利用當沖交易比例作為散戶情緒的反向指標。當沖比例異常偏高（散戶過度投機）時逆向賣出，當沖比例異常偏低（市場冷清）時逆向買入。透過 Z-Score 標準化當沖比例，以統計閾值觸發交易訊號。

## 類型

籌碼面

## 學理來源

### 學術文獻

1. **Barber, B.M. & Odean, T. (2000)**. "Trading Is Hazardous to Your Wealth: The Common Stock Investment Performance of Individual Investors." *Journal of Finance*, 55(2), 773-800.
   - 核心發現：散戶頻繁交易的績效顯著低於大盤，交易越頻繁績效越差

2. **Barber, B.M., Lee, Y.T., Liu, Y.J., & Odean, T. (2009)**. "Just How Much Do Individual Investors Lose by Trading?" *Review of Financial Studies*, 22(2), 609-632.
   - 核心發現：以台灣市場為研究對象，散戶當沖交易整體為虧損，利潤被交易成本侵蝕

3. **Kumar, A. (2009)**. "Who Gambles in the Stock Market?" *Journal of Finance*, 64(4), 1889-1933.
   - 核心發現：散戶偏好低價、高波動、高偏態的「樂透型」股票，這類偏好導致系統性虧損

### Claude 設計（原創部分）

- 當沖比例 Z-Score 標準化（用 60 天滾動窗口），將絕對比例轉換為相對異常程度
- 當沖損益方向作為輔助信號（SellAmount - BuyAmount）
- Z-Score 閾值逆向交易（> 2.0 賣出，< -1.5 買入），利用散戶過度交易的反向指標性

## 買賣條件

### 買入條件（signal = 1）

- 當沖比例 Z-Score < `oversold_z`（預設 -1.5）
- 當沖比例在 `min_day_trade_ratio` ~ `max_day_trade_ratio` 範圍內（過濾冷門股與投機股）

### 賣出條件（signal = -1）

- 當沖比例 Z-Score > `overbought_z`（預設 2.0）
- 當沖比例在合理範圍內

### 過濾條件

- 當沖比例 < `min_day_trade_ratio`（0.01）：冷門股，當沖資料不具統計意義
- 當沖比例 > `max_day_trade_ratio`（0.50）：投機股，價格行為異常

## 參數說明

| 參數 | 預設值 | 合理範圍 | 說明 |
|------|--------|----------|------|
| `zscore_window` | 60 | 20-120 | Z-Score 滾動窗口（交易日），越長越穩定但越遲鈍 |
| `overbought_z` | 2.0 | 1.5-3.0 | 過熱閾值（賣出），越高越保守 |
| `oversold_z` | -1.5 | -2.5 ~ -1.0 | 過冷閾值（買入），越低越保守 |
| `min_day_trade_ratio` | 0.01 | 0.005-0.05 | 最低當沖比例，過濾冷門股 |
| `max_day_trade_ratio` | 0.50 | 0.30-0.80 | 最高當沖比例，過濾投機股 |

## 資料需求

- `chip_margin` 表：當沖比例（`DayTradeRatio`）、當沖買賣金額（`DayTradeBuyAmount` / `DayTradeSellAmount`）
- 或由 `volume` 欄位與 `day_trade_volume` 計算

## 注意事項

- 當沖資料的可用性因個股而異，部分冷門股可能無當沖資料
- Z-Score 滾動窗口初期（前 `zscore_window` 天）無訊號
- 策略適用於有一定交易量的個股，ETF 和冷門股不適用
- 不對稱閾值設計（買入 -1.5 vs 賣出 2.0）反映散戶過度交易的不對稱分佈
