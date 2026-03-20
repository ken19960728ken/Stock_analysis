# 機器學習選股（MLFactorStrategy）

> 類型：ML 多因子 ｜ 檔案：`analysis/strategies/ml_factor.py`

## 核心邏輯

使用 LightGBM 模型對多因子進行非線性組合，預測前瞻 N 天報酬的分位數（好/中/差），選擇預測為最佳分位的股票買入。

## 參數說明

| 參數 | 預設值 | 型別 | 說明 |
|------|--------|------|------|
| `forward_days` | 5 | int | 前瞻天數 |
| `buy_quantile` | 2 | int | 買入分位標籤 |
| `sell_quantile` | 0 | int | 賣出分位標籤 |

### 參數詳解

- **`forward_days`**（前瞻天數）
  - 預測未來 N 天的報酬率
  - 5 天 → 約一週，短線；10 天 → 波段；20 天 → 中線
  - 建議範圍：5 ~ 20

- **`buy_quantile`**（買入分位標籤）
  - 3 分位時：0=差, 1=中, 2=好；預設 2
  - 建議：設為最高分位

- **`sell_quantile`**（賣出分位標籤）
  - 預設 0（3 分位中的「差」）
  - 建議：設為最低分位

### 模型特徵

| 特徵 | 說明 |
|------|------|
| return_5d | 5 日報酬率 |
| return_20d | 20 日報酬率 |
| volatility_20d | 20 日波動率 |
| volume_ratio | 成交量比（vs 20 日均量） |
| rsi | RSI(14) |
| macd_hist | MACD Histogram |
| ma20_slope | MA20 斜率 |
| bb_pct | Bollinger %B |
| per | 本益比（選用） |
| pbr | 股價淨值比（選用） |
| dividend_yield | 殖利率（選用） |
| institutional_net | 法人淨買超（選用） |

### 簡化邏輯（無 pred_label 時）

- 當資料未包含 ML 模型預測結果時，使用 RSI + MACD + 成交量的連續分數組合
- RSI 使用 Wilder 平滑法，分數 = `(50 - RSI) / 50`
- 使用邊緣觸發：只在分數**跨越**閾值時產生訊號（0.3 買入、-0.3 賣出）

### 注意事項

- 需要安裝 `lightgbm` 套件（含 libomp 依賴）
- 使用 TimeSeriesSplit CV 避免前瞻偏差
- Walk-Forward 回測提供更真實的績效評估

## 買賣條件

- **買入**：模型預測為最佳分位（或分數跨越 0.3）
- **賣出**：模型預測為最差分位（或分數跨越 -0.3）

## 學理基礎

Gu, Kelly & Xiu (2020) *Empirical Asset Pricing via Machine Learning* 以 LightGBM/Neural Network 等 ML 方法預測股票報酬，證明 ML 方法在多因子框架下顯著優於線性模型。本策略使用 LightGBM + Walk-Forward 驗證。

## 參考文獻

| # | 來源 | 說明 | PDF |
|---|------|------|-----|
| 1 | Gu, S., Kelly, B. & Xiu, D. (2020). *Empirical Asset Pricing via Machine Learning*. Review of Financial Studies, 33(5). | ML 資產定價 | [PDF](gu-kelly-xiu-2020-ml-asset-pricing.pdf) |

## Code Review 修復記錄

| # | 嚴重度 | 問題 | 修復狀態 |
|---|--------|------|---------|
| 1 | **HIGH** | 買入條件 RSI<30 + MACD>0 互相矛盾 → 改為連續分數（非二元） | ✓ 已修復 |
| 2 | MEDIUM | RSI 使用 SMA → 改用 Wilder 平滑法 | ✓ 已修復 |
| 19 | MEDIUM | 分數持續 ≥ 0.3 時每根 K 線都標記買入 → 改邊緣觸發 | ✓ 已修復 |
