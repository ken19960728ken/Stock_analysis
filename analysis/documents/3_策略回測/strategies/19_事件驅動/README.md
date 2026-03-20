# 事件驅動（EventDrivenStrategy）

> 類型：事件面 ｜ 檔案：`analysis/strategies/event_driven.py`

## 核心邏輯

除息後折價買入，持有等待填息獲利。

## 參數說明

| 參數 | 預設值 | 型別 | 說明 |
|------|--------|------|------|
| `event_type` | "dividend" | str | 事件類型 |
| `entry_days_after` | 3 | int | 除息日後 N 天買入（等價格穩定） |
| `exit_days_after` | 60 | int | 持有天數（填息通常需 1-2 個月） |
| `min_dividend_yield` | 2.0 | float | 最低殖利率門檻（%） |

### 參數詳解

- **`event_type`**（事件類型）
  - `"dividend"` → 除息事件（台股 6~9 月為除息旺季）

- **`entry_days_after`**（除息後進場天數）
  - 除息日後 N 個交易日買入（等除息跳空價格穩定）
  - 3 天 → 等待短期賣壓消化後進場
  - 建議範圍：1 ~ 10

- **`exit_days_after`**（持有天數）
  - 買入後持有 N 天賣出
  - 60 天 → 約 3 個月，等待填息
  - 建議範圍：20 ~ 120

- **`min_dividend_yield`**（最低殖利率門檻）
  - 使用**除息前一日收盤價**計算殖利率（除息日收盤價已扣股利，會高估）
  - 2.0% → 過濾小配息股
  - 建議範圍：1.5 ~ 5.0

### 除息策略邏輯

- 除息日後折價買入 → 持有等待填息 → 填息完成獲利
- 填息速度快的股票 → 策略表現好
- 填息失敗或花很久才填息 → 策略虧損

## 買賣條件

- **買入**：除息日後 N 天 + 殖利率 > 門檻
- **賣出**：持有達 exit_days_after 天

## 學理基礎

MacKinlay (1997) *Event Studies in Economics and Finance* 是事件研究方法論的權威綜述。在台股應用中，除息（Ex-dividend）和財報公告是兩大事件。Ball & Brown (1968) *An Empirical Evaluation of Accounting Income Numbers* 開創了盈餘公告事件研究。

## 參考文獻

| # | 來源 | 說明 | PDF |
|---|------|------|-----|
| 1 | MacKinlay, A.C. (1997). *Event Studies in Economics and Finance*. Journal of Economic Literature, 35(1). | 事件研究方法論 | 付費牆 |
| 2 | Ball, R. & Brown, P. (1968). *An Empirical Evaluation of Accounting Income Numbers*. Journal of Accounting Research, 6(2). | 盈餘公告效應 | — (經典論文) |

## Code Review 修復記錄

| # | 嚴重度 | 問題 | 修復狀態 |
|---|--------|------|---------|
| 16 | MEDIUM | 殖利率用除息日收盤價（已扣股利）計算 → 改用前一日收盤價 | ✓ 已修復 |
