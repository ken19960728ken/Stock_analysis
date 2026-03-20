# 股權集中度（OwnershipConcentrationStrategy）

> 類型：籌碼面 ｜ 檔案：`analysis/strategies/ownership_concentration.py`

## 核心邏輯

大股東持股比例增加 + 股東人數減少 → 籌碼集中在大戶手中 → 買入。反之（大股東減持 + 散戶增加）→ 賣出。

## 參數說明

| 參數 | 預設值 | 型別 | 說明 |
|------|--------|------|------|
| `holder_increase_threshold` | 1.0 | float | 持股比例增加門檻（百分點） |
| `shareholder_decrease_threshold` | -3.0 | float | 股東人數變化門檻（%） |
| `lookback_periods` | 4 | int | 回溯期數 |

### 參數詳解

- **`holder_increase_threshold`**（持股比例增加門檻）
  - 大股東（400 張以上）持股比例需增加的百分點數
  - 1.0 表示持股比例從 25% 增加到 26% 以上才觸發
  - 0.5 → 更靈敏；2.0 → 更嚴格
  - 建議範圍：0.3 ~ 3.0

- **`shareholder_decrease_threshold`**（股東人數變化門檻）
  - 股東人數需減少的比例（負值）
  - -3.0 表示股東人數需減少 3% 以上
  - 建議範圍：-10.0 ~ -1.0

- **`lookback_periods`**（回溯期數）
  - 與幾期前的數據比較（資料通常為週頻）
  - 4 表示與 4 週前比較
  - 建議範圍：2 ~ 8

### 注意事項

- 股權分散表為每週公布一次，資料頻率較低
- 需與價量配合觀察，籌碼集中但股價不動可能是主力在吸貨階段

## 買賣條件

- **買入**：大戶持股比例上升 + 散戶人數減少 → 籌碼集中
- **賣出**：大戶減持 + 散戶增加 → 籌碼鬆動

## 學理基礎

Shleifer & Vishny (1986) *Large Shareholders and Corporate Control* 論證大股東持股集中度與公司價值正相關。台股的持股分散表（股東人數與持股比例）可觀察主力/大戶的進出。

## 參考文獻

| # | 來源 | 說明 | PDF |
|---|------|------|-----|
| 1 | Shleifer, A. & Vishny, R.W. (1986). *Large Shareholders and Corporate Control*. Journal of Political Economy, 94(3). | 大股東與公司控制 | 付費牆 |
