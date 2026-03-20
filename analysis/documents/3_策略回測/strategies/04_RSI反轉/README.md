# RSI 反轉（RSIReversalStrategy）

> 類型：技術面 ｜ 檔案：`analysis/strategies/rsi_reversal.py`

## 核心邏輯

RSI 進入超賣區後回升時買入，進入超買區後回落時賣出。

## 參數說明

| 參數 | 預設值 | 型別 | 說明 |
|------|--------|------|------|
| `period` | 14 | int | RSI 計算週期 |
| `oversold` | 30 | int | 超賣門檻 |
| `overbought` | 70 | int | 超買門檻 |

### 參數詳解

- **`period`**（RSI 計算週期）
  - Welles Wilder 原始建議值為 14
  - 使用 Wilder Smoothing（等效於 2N-1 天的 EMA）
  - 越小波動越大、越靈敏；越大越平滑
  - 建議範圍：7 ~ 21

- **`oversold`**（超賣門檻）
  - RSI 低於此值視為超賣（市場過度恐慌）
  - 30 是經典值，強勢股可用 40，弱勢股可用 20
  - 建議範圍：20 ~ 40

- **`overbought`**（超買門檻）
  - RSI 高於此值視為超買（市場過度樂觀）
  - 70 是經典值，強勢股可用 80，弱勢股可用 60
  - 建議範圍：60 ~ 80

### 注意事項

- 強趨勢行情中 RSI 可能長期維持在超買/超賣區，反轉策略效果不佳
- 適合盤整行情使用
- 搭配趨勢過濾（MA200）避免逆勢操作

## 買賣條件

- **買入**：RSI < 30（超賣）→ 反轉買入
- **賣出**：RSI > 70（超買）→ 賣出

## 學理基礎

Welles Wilder 於 1978 年在 *New Concepts in Technical Trading Systems* 中提出 RSI（Relative Strength Index），使用 Wilder 平滑法（指數移動平均的變體）計算相對強度。

Wilder 平滑法的遞迴公式為 `avg = prev_avg × (n-1)/n + current/n`，等價於 `EMA(alpha=1/n)`，與 SMA 不同。

## 參考文獻

| # | 來源 | 說明 | PDF |
|---|------|------|-----|
| 1 | Wilder, J.W. (1978). *New Concepts in Technical Trading Systems*. Trend Research. | RSI + Parabolic SAR + ATR 原創著作 | — (書籍) |
