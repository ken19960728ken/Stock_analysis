# 法人跟單（InstitutionalStrategy）

> 類型：籌碼面 ｜ 檔案：`analysis/strategies/institutional.py`

## 核心邏輯

三大法人連續 N 日淨買超 + 價格在 MA20 上方時買入，連續 N 日淨賣超時賣出。支援拆分單一法人（外資/投信/自營商）追蹤。

## 參數說明

| 參數 | 預設值 | 型別 | 說明 |
|------|--------|------|------|
| `consecutive_days` | 5 | int | 連續天數門檻 |
| `focus` | "all" | str | 追蹤法人類型（all/foreign/trust/dealer） |
| `require_all_three` | False | bool | 是否要求三法人同時買超 |

### 參數詳解

- **`consecutive_days`**（連續天數門檻）
  - 法人必須連續 N 天買超才觸發買入訊號
  - 5 天 → 較保守，確認法人持續佈局意圖
  - 3 → 中等靈敏度
  - 7 → 非常保守
  - 建議範圍：2 ~ 7

- **`focus`**（追蹤法人類型）
  - `"all"` → 合計三大法人淨買超（預設）
  - `"foreign"` → 僅追蹤外資
  - `"trust"` → 僅追蹤投信
  - `"dealer"` → 僅追蹤自營商
  - 外資適合大型權值股，投信適合中小型成長股

- **`require_all_three`**（是否要求三法人同時買超）
  - False → 只看 focus 指定的法人（預設）
  - True → 三大法人必須同時買超才觸發

### 欄位偵測順序

1. `institutional_net_buy`（合計淨買超，優先）
2. 含 `net` + `buy`/`foreign`/`institutional` 的欄位（淨買超）
3. `法人買賣超` 等合計欄位（最後 fallback）

## 買賣條件

- **買入**：法人連續 N 日買超 + 股價 > MA20
- **賣出**：法人連續 N 日賣超

### 注意事項

- 法人包含外資、投信、自營商三者合計
- 大型股法人影響力較大，中小型股效果可能不明顯
- 需搭配成交量觀察，低量的法人買超可能不具參考性

## 學理基礎

Nofsinger & Sias (1999) *Herding and Feedback Trading by Institutional and Individual Investors* 發現機構投資人的交易行為具有正向回饋特性，且其持股變動能預測未來報酬。台股三大法人（外資、投信、自營商）買賣超為台灣市場特有的籌碼面資訊。

## 參考文獻

| # | 來源 | 說明 | PDF |
|---|------|------|-----|
| 1 | Nofsinger, J.R. & Sias, R.W. (1999). *Herding and Feedback Trading by Institutional and Individual Investors*. Journal of Finance, 54(6). | 法人羊群效應與報酬預測 | 付費牆 |

## Code Review 修復記錄

| # | 嚴重度 | 問題 | 修復狀態 |
|---|--------|------|---------|
| 17 | MEDIUM | Fallback 偵測 `"buy"` 誤取單邊買量 → 優先匹配含 `"net"` 的淨買超欄位 | ✓ 已修復 |
