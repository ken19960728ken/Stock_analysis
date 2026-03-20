# 波動率壓縮突破（VolatilitySqueezeStrategy）

> 類型：技術面 ｜ 檔案：`analysis/strategies/volatility_squeeze.py`

## 核心邏輯

Bollinger Bands 收縮至 Keltner Channel 之內形成 Squeeze 狀態，突破後順勢進場。

## 參數說明

| 參數 | 預設值 | 型別 | 說明 |
|------|--------|------|------|
| `bb_period` | 20 | int | Bollinger Bands 週期 |
| `bb_std` | 2.0 | float | Bollinger Bands 標準差倍數 |
| `kc_period` | 20 | int | Keltner Channel 週期 |
| `kc_mult` | 1.5 | float | Keltner Channel ATR 倍數 |
| `atr_period` | 14 | int | ATR 計算週期 |
| `squeeze_min_days` | 5 | int | 壓縮最少持續天數 |
| `rsi_threshold` | 50 | int | RSI 動量確認門檻 |
| `exit_ema_period` | 20 | int | 出場 EMA 期數 |
| `trend_period` | 60 | int | 趨勢過濾均線期數 |
| `atr_stop_multiple` | 2.0 | float | ATR 停損倍數 |

### 參數詳解

- **`bb_period`** / **`bb_std`**：同 Bollinger 策略，建議範圍 10~30 / 1.5~3.0

- **`kc_period`**（Keltner Channel 週期）
  - Keltner Channel 的 EMA 週期，建議範圍：10 ~ 30

- **`kc_mult`**（ATR 倍數）
  - Keltner Channel 寬度 = EMA ± kc_mult × ATR
  - 1.5 為常用值，越大通道越寬、Squeeze 越不容易出現
  - 建議範圍：1.0 ~ 2.5

- **`squeeze_min_days`**（壓縮最少持續天數）
  - Squeeze 狀態需持續 N 天以上才算有效壓縮
  - 5 → 避免短暫的假壓縮觸發訊號
  - 建議範圍：3 ~ 10

- **`rsi_threshold`**（RSI 動量確認門檻）
  - 突破時 RSI 需高於此值，確認動量方向
  - 50 → 中性線以上，確認多頭動量
  - 建議範圍：40 ~ 60

- **`exit_ema_period`**（出場 EMA 期數）
  - 跌破此 EMA 觸發賣出（取代 BB 中軌作為出場基準）
  - 建議範圍：10 ~ 40

- **`trend_period`**（趨勢過濾均線期數）
  - 股價需在 SMA(trend_period) 上方才允許買入
  - 60 → 約 3 個月趨勢線
  - 建議範圍：40 ~ 120

- **`atr_stop_multiple`**（ATR 停損倍數）
  - 停損點 = 進場價 - atr_stop_multiple × ATR
  - 建議範圍：1.5 ~ 3.0

### Squeeze 判定

```
Squeeze ON = BB_upper < KC_upper 且 BB_lower > KC_lower
Squeeze OFF = Squeeze 狀態結束（BB 重新擴張超出 KC）
```

## 買賣條件

- **買入**：持續壓縮 ≥ squeeze_min_days 後解除 + 收盤 > BB 上軌 + RSI > rsi_threshold + 放量 + 股價 > SMA(trend_period)
- **賣出**：跌破 EMA(exit_ema_period) 或重新進入持續壓縮（買賣同 bar 時買入優先）

## 學理基礎

John Carter (2005) *Mastering the Trade* 提出 Squeeze（BB 收窄進入 KC 通道）作為波動率壓縮突破訊號。當 BB 寬度小於 KC 寬度時，市場處於低波動壓縮狀態，突破後往往產生強勁走勢。

## 參考文獻

| # | 來源 | 說明 | PDF |
|---|------|------|-----|
| 1 | Carter, J. (2005). *Mastering the Trade*. McGraw-Hill. | Squeeze 指標原創著作 | — (書籍) |

## Code Review 修復記錄

| # | 嚴重度 | 問題 | 修復狀態 |
|---|--------|------|---------|
| 10 | MEDIUM | 同一 bar 買入可能被賣出覆蓋 → 買入優先（`sell & ~buy`） | ✓ 已修復 |
