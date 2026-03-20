# Dual Thrust（DualThrustStrategy）

> 類型：技術面 ｜ 檔案：`analysis/strategies/dual_thrust.py`

## 核心邏輯

基於前 N 日的高低點計算動態上下軌，突破上軌買入，跌破下軌賣出。

## 參數說明

| 參數 | 預設值 | 型別 | 說明 |
|------|--------|------|------|
| `lookback` | 5 | int | 計算區間 N 日 |
| `k1` | 0.7 | float | 上軌係數 |
| `k2` | 0.7 | float | 下軌係數 |
| `volume_ratio` | 1.2 | float | 成交量確認倍數（vs 20日均量） |

### 參數詳解

- **`lookback`**（計算區間 N 日）
  - 回溯 N 日計算最高價與最低價的 Range
  - 越大 → 通道越寬，訊號越少但越可靠
  - 越小 → 通道越窄，訊號越多但假突破多
  - 建議範圍：3 ~ 10

- **`k1`**（上軌係數）
  - 上軌 = 開盤價 + k1 × Range
  - 越大 → 上軌越高，需要更大漲幅才觸發買入
  - 建議範圍：0.3 ~ 0.8

- **`k2`**（下軌係數）
  - 下軌 = 開盤價 - k2 × Range
  - 越大 → 下軌越低，需要更大跌幅才觸發賣出
  - 建議範圍：0.3 ~ 0.8
  - **k1 ≠ k2 可實現非對稱突破**（例如容易做多但不容易做空）

- **`volume_ratio`**（成交量確認倍數）
  - 突破時成交量需超過 20 日均量的倍數
  - 1.2 → 溫和放量確認，避免無量假突破
  - 建議範圍：1.0 ~ 2.0

### Range 計算（排除當日，避免 Look-Ahead Bias）

```
HH = max(High[t-N : t-1])    # 前 N 日最高價（不含當日）
HC = max(Close[t-N : t-1])   # 前 N 日最高收盤
LL = min(Low[t-N : t-1])     # 前 N 日最低價（不含當日）
LC = min(Close[t-N : t-1])   # 前 N 日最低收盤
Range = max(HH - LC, HC - LL)
```

## 買賣條件

- **買入**：收盤價 > 開盤價 + k1 × Range + 放量確認
- **賣出**：收盤價 < 開盤價 - k2 × Range

## 學理基礎

Dual Thrust 是經典日內突破策略，由 Michael Chalek 開發，核心概念出自通道突破（Channel Breakout）。與 Turtle Trading（Richard Dennis, 1983）使用的 Donchian Channel 突破同源。Linda Raschke & Larry Connors (1995) *Street Smarts* 記錄了類似的短線突破系統。

## 參考文獻

| # | 來源 | 說明 | PDF |
|---|------|------|-----|
| 1 | Raschke, L.B. & Connors, L. (1995). *Street Smarts: High Probability Short-Term Trading Strategies*. M. Gordon Publishing. | 短線突破系統集大成 | — (書籍) |

## Code Review 修復記錄

| # | 嚴重度 | 問題 | 修復狀態 |
|---|--------|------|---------|
| 5 | **HIGH** | `rolling(n).max/min()` 包含當日資料（Look-Ahead Bias）→ 加 `shift(1)` 排除當日 | ✓ 已修復 |
