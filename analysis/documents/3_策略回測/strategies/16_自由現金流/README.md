# 自由現金流（FreeCashFlowStrategy）

> 類型：基本面 ｜ 檔案：`analysis/strategies/free_cash_flow.py`

## 核心邏輯

營運現金流為正且自由現金流殖利率達標時買入。OCF 為負或 FCF Yield 不達標時賣出。

## 參數說明

| 參數 | 預設值 | 型別 | 說明 |
|------|--------|------|------|
| `fcf_yield_threshold` | 3.0 | float | FCF Yield 門檻（%） |
| `ocf_positive_required` | True | bool | 是否要求 OCF > 0 |

### 參數詳解

- **`fcf_yield_threshold`**（FCF Yield 門檻）
  - FCF Yield = 自由現金流 / 市值 × 100%
  - 自由現金流 = 營運現金流 - 資本支出
  - 3.0% 表示投資人每年可獲得 3% 的自由現金回報（原 5.0%，下調以涵蓋更多標的）
  - 建議範圍：2.0 ~ 10.0

- **`ocf_positive_required`**（是否要求 OCF > 0）
  - True → 營運現金流必須為正（本業有實際現金流入）
  - **強烈建議保持 True**：OCF 為負代表本業現金流出，即使帳面獲利也可能有財務風險

### FCF 計算

- FCF = OCF - CapEx（Jensen 1986 定義）
- 若資料含 CapEx 欄位（`CapitalExpenditure`、`capex`、`資本支出`）→ 自動扣除
- 若無 CapEx 欄位 → FCF = OCF（向後相容）
- CapEx 通常為負值，程式取絕對值後扣除

### 關鍵概念

- OCF > 淨利 → 盈餘品質好（現金收得回來）
- OCF < 淨利 → 盈餘品質差（可能是應收帳款膨脹）
- FCF > 0 → 公司有餘裕發股利、還債或再投資

## 買賣條件

- **買入**：OCF > 0 + FCF Yield > 門檻
- **賣出**：OCF 為負或 FCF Yield 不達標

## 學理基礎

Jensen (1986) *Agency Costs of Free Cash Flow* 論證自由現金流（FCF = 營業現金流 - 資本支出）是衡量企業真實獲利能力的關鍵指標。Lakonishok, Shleifer & Vishny (1994) *Contrarian Investment, Extrapolation, and Risk* 發現高現金流產出比的股票具有超額報酬。

## 參考文獻

| # | 來源 | 說明 | PDF |
|---|------|------|-----|
| 1 | Jensen, M.C. (1986). *Agency Costs of Free Cash Flow, Corporate Finance, and Takeovers*. American Economic Review, 76(2). | FCF 代理成本理論 | 付費牆 |
| 2 | Lakonishok, J., Shleifer, A. & Vishny, R.W. (1994). *Contrarian Investment, Extrapolation, and Risk*. Journal of Finance, 49(5). | 現金流因子超額報酬 | 付費牆 |

## Code Review 修復記錄

| # | 嚴重度 | 問題 | 修復狀態 |
|---|--------|------|---------|
| 3 | MEDIUM | FCF 未扣除 CapEx → 新增 CapEx 偵測，FCF = OCF - CapEx（Jensen 1986） | ✓ 已修復 |
| 20 | MEDIUM | CapEx NaN 未 fillna 導致 FCF 為 NaN → 加 `.fillna(0)` | ✓ 已修復 |
