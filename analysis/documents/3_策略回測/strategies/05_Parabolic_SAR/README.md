# Parabolic SAR（ParabolicSARStrategy）

> 類型：技術面 ｜ 檔案：`analysis/strategies/parabolic_sar.py`

## 核心邏輯

SAR 點從價格上方翻到下方（翻多）時買入，從下方翻到上方（翻空）時賣出。

## 參數說明

| 參數 | 預設值 | 型別 | 說明 |
|------|--------|------|------|
| `af` | 0.02 | float | 加速因子初始值 |
| `max_af` | 0.2 | float | 加速因子上限 |
| `adx_period` | 14 | int | ADX 計算週期 |
| `adx_threshold` | 25 | float | ADX 趨勢強度門檻（僅影響買入） |

### 參數詳解

- **`af`**（加速因子初始值，Acceleration Factor）
  - SAR 追蹤速度的起始值，每次創新高/低時增加一個 `af`
  - 0.02 是 Welles Wilder 原始設計值
  - 越大 → SAR 追蹤越快，停損越緊，但容易被震盪洗出
  - 越小 → SAR 追蹤越慢，可抓住大趨勢，但停損較遠
  - 建議範圍：0.01 ~ 0.05

- **`max_af`**（加速因子上限）
  - 限制 AF 的最大值，防止 SAR 追蹤速度無限加快
  - 0.2 是原始設計值，表示最多加速 10 次（0.02 × 10）
  - 建議範圍：0.1 ~ 0.3

- **`adx_period`**（ADX 計算週期）
  - ADX 指標的平滑週期，14 是 Wilder 原始設計值
  - 建議範圍：10 ~ 20

- **`adx_threshold`**（ADX 趨勢強度門檻）
  - ADX > 此值視為趨勢明確，**僅用於過濾買入訊號**
  - 賣出訊號不受 ADX 限制，確保止損機制永遠生效
  - 25 是經典門檻值
  - 20 → 更寬鬆，較弱趨勢也允許買入
  - 30 → 更嚴格，僅在強趨勢時入場
  - 建議範圍：15 ~ 35

### SAR 計算流程

```
1. 初始 AF = 0.02，EP = 極值點
2. SAR(t+1) = SAR(t) + AF × (EP - SAR(t))
3. 若創新高/低：AF += 0.02（不超過 max_af），更新 EP
4. 若價格穿越 SAR：翻轉方向，重置 AF
```

## 買賣條件

- **買入**：價格上穿 SAR + ADX > 閾值（趨勢明確）
- **賣出**：價格下穿 SAR（不受 ADX 限制，確保止損生效）

## 學理基礎

同樣出自 Wilder (1978)。Parabolic SAR（Stop and Reverse）是追蹤止損系統，加速因子（AF）會隨趨勢延續而遞增，使止損點加速收斂至價格。

## 參考文獻

| # | 來源 | 說明 | PDF |
|---|------|------|-----|
| 1 | Wilder, J.W. (1978). *New Concepts in Technical Trading Systems*. Trend Research. | RSI + Parabolic SAR + ATR 原創著作 | — (書籍) |

## Code Review 修復記錄

| # | 嚴重度 | 問題 | 修復狀態 |
|---|--------|------|---------|
| 4 | MEDIUM | ADX 過濾同時阻擋賣出訊號 → 賣出不受 ADX 限制，確保止損生效 | ✓ 已修復 |
| 7 | **HIGH** | 初始 `bull=True` 導致第 2 根 K 線必然觸發假買入訊號 → 過濾前 2 根 K 線 | ✓ 已修復 |
