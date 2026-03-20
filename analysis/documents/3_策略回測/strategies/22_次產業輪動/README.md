# 次產業輪動（SubIndustryRotationStrategy）

> 類型：產業面 ｜ 檔案：`analysis/strategies/sub_industry_rotation.py`

## 核心邏輯

計算各次產業的營收動能與法人流向排名，買入排名前 N 的次產業龍頭股。

## 參數說明

| 參數 | 預設值 | 型別 | 說明 |
|------|--------|------|------|
| `top_n_industries` | 3 | int | 選取前 N 個強勢次產業 |
| `max_holding_days` | 20 | int | 最大持有天數 |
| `rebalance_days` | 5 | int | 再平衡間隔 |

### 參數詳解

- **`top_n_industries`**（前 N 個產業）
  - 從 110+ 個次產業中選取排名前 N 的強勢產業
  - 3 → 集中投資前 3 強；5 → 較分散
  - 建議範圍：2 ~ 10

- **`max_holding_days`**（最大持有天數）
  - 無論訊號如何，持有超過 N 天自動賣出
  - 20 天 → 約一個月，適合中短線輪動
  - 建議範圍：10 ~ 60

- **`rebalance_days`**（再平衡間隔）
  - 每隔 N 天重新計算產業排名並調整持倉
  - 5 天 → 約每週一次
  - 建議範圍：5 ~ 20

## 買賣條件

- **買入**：股票所屬次產業排名前 N 且為該產業龍頭
- **賣出**：次產業排名跌出前 N 或持有超過 max_holding_days

## 學理基礎

Moskowitz & Grinblatt (1999) *Do Industries Explain Momentum?* 發現產業動量能解釋大部分個股動量效應，產業輪動策略具有獨立的 alpha。本策略結合營收動能 + 法人流向對次產業排名，選擇排名前列產業中的個股。

## 參考文獻

| # | 來源 | 說明 | PDF |
|---|------|------|-----|
| 1 | Moskowitz, T.J. & Grinblatt, M. (1999). *Do Industries Explain Momentum?*. Journal of Finance, 54(4). | 產業動量效應 | 付費牆 |

## Code Review 修復記錄

| # | 嚴重度 | 問題 | 修復狀態 |
|---|--------|------|---------|
| 21 | LOW | 快取欄位已宣告但未使用 → 已知 tech debt，不影響正確性 | ⏭ 已知 |
