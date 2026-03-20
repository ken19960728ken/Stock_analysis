# 多因子綜合（MultiFactorStrategy）

> 類型：技術面(40%)+籌碼面(30%)+基本面(30%) ｜ 檔案：`analysis/strategies/multi_factor.py`

## 核心邏輯

綜合技術面（RSI、MACD、MA 方向）、籌碼面（法人買賣超）、基本面（PER）三大維度加權計算分數，超過門檻買入，低於門檻賣出。

## 參數說明

| 參數 | 預設值 | 型別 | 說明 |
|------|--------|------|------|
| `tech_weight` | 0.4 | float | 技術面權重 |
| `chip_weight` | 0.3 | float | 籌碼面權重 |
| `fund_weight` | 0.3 | float | 基本面權重 |
| `buy_threshold` | 0.4 | float | 買入分數門檻 |
| `sell_threshold` | -0.2 | float | 賣出分數門檻 |
| `use_zscore` | False | bool | 是否啟用 Z-Score 標準化 |

### 參數詳解

- **`tech_weight`**（技術面權重）
  - 技術面子分數的權重，預設佔比 40%
  - 技術面因子：RSI、MACD Histogram、MA20 方向
  - 建議範圍：0.2 ~ 0.6

- **`chip_weight`**（籌碼面權重）
  - 籌碼面子分數的權重，預設佔比 30%
  - 籌碼面因子：三大法人淨買超
  - 建議範圍：0.1 ~ 0.5

- **`fund_weight`**（基本面權重）
  - 基本面子分數的權重，預設佔比 30%
  - 基本面因子：PER（本益比）
  - 建議範圍：0.1 ~ 0.5
  - **三個權重之和會自動正規化為 1.0**

- **`buy_threshold`**（買入分數門檻）
  - 加權總分超過此值才買入，分數範圍約 -1.0 ~ 1.0
  - 0.4 → 適中（原 0.6→0.4）
  - 建議範圍：0.2 ~ 0.8

- **`sell_threshold`**（賣出分數門檻）
  - 加權總分低於此值才賣出
  - -0.2 → 靈敏止損（原 -0.3→-0.2）
  - 建議範圍：-0.8 ~ 0.0

- **`use_zscore`**（是否啟用 Z-Score 標準化）
  - True → 各因子先做 Z-Score 標準化再加權，消除量綱差異
  - False → 使用原始分數（預設）

## 買賣條件

- **買入**：加權總分 > buy_threshold
- **賣出**：加權總分 < sell_threshold

## 學理基礎

Fama & French (1993) *Common Risk Factors in the Returns on Stocks and Bonds* 提出三因子模型（市場、規模、價值），後擴展為五因子（2015 年加入獲利能力 + 投資）。Carhart (1997) 加入動量因子成為四因子模型。本策略整合技術面 40% + 籌碼面 30% + 基本面 30%。

## 參考文獻

| # | 來源 | 說明 | PDF |
|---|------|------|-----|
| 1 | Fama, E.F. & French, K.R. (1993). *Common Risk Factors in the Returns on Stocks and Bonds*. Journal of Financial Economics, 33(1). | 三因子模型 | 付費牆 |
| 2 | Carhart, M.M. (1997). *On Persistence in Mutual Fund Performance*. Journal of Finance, 52(1). | 四因子模型（加入動量） | 付費牆 |

## Code Review 修復記錄

| # | 嚴重度 | 問題 | 修復狀態 |
|---|--------|------|---------|
| 18 | MEDIUM | 因子權重總和 ≠ 1 時分數膨脹 + PE/籌碼欄位偵測同上 → 加權重正規化 + 修正偵測 | ✓ 已修復 |
