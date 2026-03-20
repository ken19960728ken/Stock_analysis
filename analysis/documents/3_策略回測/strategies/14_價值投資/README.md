# 價值投資（ValueInvestingStrategy）

> 類型：基本面 ｜ 檔案：`analysis/strategies/value_investing.py`

## 核心邏輯

同時滿足低本益比、高殖利率、營收正成長三個條件時買入。任一條件不滿足時賣出。

## 參數說明

| 參數 | 預設值 | 型別 | 說明 |
|------|--------|------|------|
| `pe_threshold` | 15 | int | P/E 低估門檻 |
| `dividend_yield_threshold` | 3.0 | float | 殖利率最低要求（%） |
| `revenue_growth_threshold` | 0 | int | 營收成長門檻（%） |

### 參數詳解

- **`pe_threshold`**（P/E 低估門檻）
  - 本益比需低於此值才視為低估
  - 15 是台股傳統的合理水位（約 6.7% 盈餘殖利率）
  - 10 → 非常嚴格，只選極度低估股；20 → 較寬鬆
  - 建議範圍：8 ~ 25
  - 不同產業合理 P/E 差異大：金融 8~12、傳產 10~15、科技 15~25

- **`dividend_yield_threshold`**（殖利率最低要求）
  - 現金殖利率需高於此值
  - 3.0% 是台股平均水準
  - 建議範圍：2.0 ~ 6.0

- **`revenue_growth_threshold`**（營收成長門檻）
  - 最新月營收年增率需高於此值（%）
  - 0 表示營收不衰退即可
  - 建議範圍：-20 ~ 30

## 買賣條件

- **買入**：低 PER + 高殖利率 + 營收正成長
- **賣出**：任一條件不滿足

## 學理基礎

Benjamin Graham (1949) *The Intelligent Investor* 奠定價值投資哲學。Fama & French (1992) *The Cross-Section of Expected Stock Returns* 以 HML（高帳面市值比 vs 低帳面市值比）因子驗證價值溢酬的存在。

## 參考文獻

| # | 來源 | 說明 | PDF |
|---|------|------|-----|
| 1 | Graham, B. (1949). *The Intelligent Investor*. Harper & Brothers. | 價值投資經典 | — (書籍) |
| 2 | Fama, E.F. & French, K.R. (1992). *The Cross-Section of Expected Stock Returns*. Journal of Finance, 47(2). | 價值因子（HML）的學術驗證 | 付費牆 |

## Code Review 修復記錄

| # | 嚴重度 | 問題 | 修復狀態 |
|---|--------|------|---------|
| 14 | MEDIUM | `"pe" in c.lower()` 誤中 `capex` 等 → 改精確匹配清單 | ✓ 已修復 |
