# Database Schema

本文件記錄本專案所有 DB 表的 schema 與重要規則。

## 重要規則

### 新增資料來源規則（Data Source Verification Protocol）

**抓取新 FinMind 資料前，必須依序完成以下步驟**：

1. **先呼叫 API 取樣**：對目標 API 實際呼叫一次（如 `fm.method(stock_id='2330', start_date='...')`），記錄回傳的 `df.columns` 和所有分類欄位的唯一值（如 `type`、`name`）。
2. **比對命名**：將 API 實際回傳的欄位名稱與你預期的名稱做比對。FinMind 的命名**沒有統一慣例**（有 PascalCase、有縮寫、有全名），絕對不能假設。
3. **更新 Schema 文件**：
   - `memory/finmind-api-schema.md`：加入新 API 的實際欄位
   - `docs/database-schema.md`：加入新 DB 表的 schema
4. **寫入 FOCUS_METRICS 或欄位映射時**，只使用步驟 1 中確認存在的名稱。
5. **寫入 DB 前**，用 `df.columns` 確認欄位存在，不存在則 log warning。

**禁止行為**：
- ❌ 假設 API 回傳的 type/欄位名稱（如假設有 `NetIncome` 但實際是 `IncomeAfterTaxes`）
- ❌ 在 FOCUS_METRICS 或欄位映射中使用未經 API 驗證的名稱
- ❌ 靜默過濾不匹配的 type（應 log warning）

**歷史教訓**：
- `month_revenue_year_on_year`：假設 FinMind 月營收 API 有此欄位，實際不存在，導致 20+ 處引用靜默失效
- FOCUS_METRICS 中 5 個 type 名稱錯誤（NetIncome/EarningsPerShare/TotalLiabilities/TotalEquity/CapitalExpenditure），導致這些資料從未被寫入 DB
