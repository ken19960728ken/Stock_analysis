# MA 交叉（MACrossStrategy）

> 類型：技術面 ｜ 檔案：`analysis/strategies/ma_cross.py`

## 核心邏輯

短期均線上穿長期均線時買入（黃金交叉），下穿時賣出（死亡交叉）。

## 參數說明

| 參數 | 預設值 | 型別 | 說明 |
|------|--------|------|------|
| `fast_period` | 5 | int | 快速均線週期（短天期 SMA） |
| `slow_period` | 20 | int | 慢速均線週期（長天期 SMA） |

### 參數詳解

- **`fast_period`**（快速均線週期）
  - 代表短期趨勢方向，越小越靈敏、訊號越多但雜訊也越多
  - 常用值：5（一週）、10（兩週）、20（一個月）
  - 建議範圍：3 ~ 30

- **`slow_period`**（慢速均線週期）
  - 代表中長期趨勢方向，越大越穩定但反應越慢
  - 常用值：20（一個月）、60（一季）、120（半年）、240（一年）
  - 建議範圍：20 ~ 240
  - **必須大於 `fast_period`**

### 經典組合

| 組合 | 特性 |
|------|------|
| 5/20 | 短線操作，訊號頻繁 |
| 10/60 | 中線波段，適合月操作 |
| 20/60 | 中線趨勢，穩健型 |
| 60/240 | 長線趨勢，年度級別 |

## 買賣條件

- **買入**：短期 MA 上穿長期 MA（黃金交叉）
- **賣出**：短期 MA 下穿長期 MA（死亡交叉）

## 學理基礎

移動平均線交叉是最古老的趨勢跟蹤方法之一。Brock, Lakonishok & LeBaron (1992) 在 *Simple Technical Trading Rules and the Stochastic Properties of Stock Returns* 中，以道瓊指數 90 年資料驗證 MA 交叉規則具統計顯著性。

## 參考文獻

| # | 來源 | 說明 | PDF |
|---|------|------|-----|
| 1 | Brock, Lakonishok & LeBaron (1992). *Simple Technical Trading Rules and the Stochastic Properties of Stock Returns*. Journal of Finance, 47(5). | MA/Support-Resistance 規則在美股的實證有效性 | 付費牆 |
