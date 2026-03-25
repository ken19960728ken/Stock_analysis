# Database Schema — Supabase PostgreSQL

> 最後更新：2026-03-25
>
> 本文件記錄 Supabase 資料庫中所有資料表的 schema、欄位說明與約束。
> **新增或修改資料表後，必須同步更新本文件。**

## 總覽

| 表名 | 說明 | 資料來源 | 大小 | Unique Key |
|---|---|---|---|---|
| `daily_price` | 日K線 OHLCV | Yahoo Finance / FinMind | 284 MB | `(stock_id, date)` |
| `weekly_price` | 週K線 OHLCV | Yahoo Finance | 36 MB | `(stock_id, date)` |
| `monthly_price` | 月K線 OHLCV | Yahoo Finance | 8 MB | `(stock_id, date)` |
| `chip_institutional` | 三大法人買賣超 | FinMind (pivot) | 333 MB | `(stock_id, date)` |
| `chip_margin` | 融資融券 | FinMind | 451 MB | `(stock_id, date)` |
| `chip_shareholding` | 外資持股 | FinMind | 421 MB | `(stock_id, date)` |
| `chip_holding_pct` | 持股分級表 | FinMind | 1,179 MB | `(stock_id, date, HoldingSharesLevel)` |
| `chip_securities_lending` | 借券成交明細 | FinMind | 97 MB | `(stock_id, date, transaction_type)` |
| `chip_short_sale` | 借券賣出餘額 | FinMind | 435 MB | `(stock_id, date)` |
| `chip_broker` | 8大外資券商分點（聚合） | FinMind (Sponsor) | 18 MB | `(stock_id, date, securities_trader_id)` |
| `chip_gov_bank` | 官股行庫買賣超 | FinMind (Sponsor) | 69 MB | `(stock_id, date, bank_name)` |
| `stock_per` | 本益比/股價淨值比/殖利率 | FinMind | 226 MB | `(stock_id, date)` |
| `market_value` | 市值 | FinMind | 184 MB | `(stock_id, date)` |
| `month_revenue` | 月營收 | FinMind | 12 MB | `(stock_id, date, country)` |
| `financial_reports` | 財務報表（損益表+資產負債表+現金流量表） | FinMind | 27 MB | `(stock_id, date, type)` |
| `dividend_history` | 股利紀錄 | Yahoo Finance | 2 MB | `(stock_id, date, dividend)` |
| `dividend_result` | 除權除息結果 | FinMind | 1 MB | `(stock_id, date)` |
| `day_trading` | 當日沖銷交易 | FinMind | 137 MB | `(stock_id, date)` |
| `total_return_index` | 含息報酬指數 | FinMind | 120 KB | `(index_id, date)` |
| `twstock_code` | 股票代碼元資料 | twstock | 7 MB | `(商品代號)` |
| `securities_trader_info` | 券商基本資訊（靜態） | FinMind | 144 KB | `(securities_trader_id)` |
| `stock_delisting` | 下市櫃紀錄 | FinMind | 48 KB | `(stock_id, date)` |
| `recommendation_history` | 選股推薦追蹤 | 系統產生 | 208 KB | `(report_date, stock_id)` |
| `scanner_run_log` | Scanner 執行日誌 | 系統產生 | 64 KB | `(run_date, scanner_name, started_at)` |
| `scan_progress` | 掃描進度（斷點續傳） | 系統產生 | 3 MB | `(stock_id, table_name)` |

---

## 價格資料

### `daily_price` — 日K線

| 欄位 | 型別 | 說明 |
|---|---|---|
| `date` | date | 交易日期 |
| `stock_id` | text | 股票代碼（4-5 碼） |
| `open` | double precision | 開盤價 |
| `high` | double precision | 最高價 |
| `low` | double precision | 最低價 |
| `close` | double precision | 收盤價 |
| `volume` | bigint | 成交量（股） |

- **Unique Key**: `(stock_id, date)`
- **來源**: Yahoo Finance（PriceScanner）/ FinMind（DailyUpdater，欄位映射 `max→high`, `min→low`, `Trading_Volume→volume`）
- **更新頻率**: 每日

### `weekly_price` — 週K線

欄位同 `daily_price`。

- **Unique Key**: `(stock_id, date)`
- **來源**: Yahoo Finance（WeeklyPriceScanner）

### `monthly_price` — 月K線

欄位同 `daily_price`。

- **Unique Key**: `(stock_id, date)`
- **來源**: Yahoo Finance（MonthlyPriceScanner）

---

## 籌碼面 — 法人

### `chip_institutional` — 三大法人買賣超

| 欄位 | 型別 | 說明 |
|---|---|---|
| `date` | date | 交易日期 |
| `stock_id` | text | 股票代碼 |
| `foreign_investors_buy` | bigint | 外資買進（股） |
| `foreign_investors_sell` | bigint | 外資賣出（股） |
| `investment_trust_buy` | bigint | 投信買進（股） |
| `investment_trust_sell` | bigint | 投信賣出（股） |
| `dealer_buy` | bigint | 自營商買進（股） |
| `dealer_sell` | bigint | 自營商賣出（股） |

- **Unique Key**: `(stock_id, date)`
- **來源**: FinMind `taiwan_stock_institutional_investors`，原始為長格式（name/buy/sell），由 `_pivot_institutional()` pivot 為寬格式
- **備註**: 合併 `Foreign_Dealer_Self` 到 `foreign_investors`，`Dealer_Hedging` 到 `dealer`

### `chip_broker` — 8大外資券商分點（聚合）

| 欄位 | 型別 | 說明 |
|---|---|---|
| `stock_id` | text | 股票代碼 |
| `date` | date | 交易日期 |
| `securities_trader_id` | text | 券商代碼（如 1650=瑞銀） |
| `securities_trader` | text | 券商名稱 |
| `total_buy` | bigint | 當日總買進量（股，所有價位加總） |
| `total_sell` | bigint | 當日總賣出量（股，所有價位加總） |
| `net` | bigint | 淨買超（`total_buy - total_sell`） |

- **Unique Key**: `(stock_id, date, securities_trader_id)`
- **來源**: FinMind `taiwan_stock_trading_daily_report`（Sponsor），用 `securities_trader_id` 查詢 8 大外資，聚合後寫入
- **追蹤的外資券商**: 瑞銀(1650)、高盛(1480)、摩根士丹利(1470)、摩根大通(8440)、美林(1440)、花旗環球(1590)、麥格理(1360)、野村(1560)
- **更新頻率**: 每日（T+1 延遲）

### `chip_gov_bank` — 官股行庫買賣超

| 欄位 | 型別 | 說明 |
|---|---|---|
| `date` | date | 交易日期 |
| `stock_id` | text | 股票代碼 |
| `buy_amount` | double precision | 買進金額（元） |
| `sell_amount` | double precision | 賣出金額（元） |
| `buy` | bigint | 買進股數 |
| `sell` | bigint | 賣出股數 |
| `bank_name` | text | 行庫名稱（兆豐/第一/華南/臺銀/合庫/土銀/台企銀/彰銀） |

- **Unique Key**: `(stock_id, date, bank_name)`
- **來源**: FinMind `taiwan_stock_government_bank_buy_sell`（Sponsor）
- **備註**: 全市場資料，API 不帶 stock_id，每日約 14,000 筆
- **更新頻率**: 每日

---

## 籌碼面 — 融資融券

### `chip_margin` — 融資融券

| 欄位 | 型別 | 說明 |
|---|---|---|
| `date` | date | 交易日期 |
| `stock_id` | text | 股票代碼 |
| `MarginPurchaseBuy` | bigint | 融資買進 |
| `MarginPurchaseSell` | bigint | 融資賣出 |
| `MarginPurchaseCashRepayment` | bigint | 融資現金償還 |
| `MarginPurchaseTodayBalance` | bigint | 融資今日餘額 |
| `MarginPurchaseYesterdayBalance` | bigint | 融資昨日餘額 |
| `MarginPurchaseLimit` | bigint | 融資限額 |
| `ShortSaleBuy` | bigint | 融券買進 |
| `ShortSaleSell` | bigint | 融券賣出 |
| `ShortSaleCashRepayment` | bigint | 融券現金償還 |
| `ShortSaleTodayBalance` | bigint | 融券今日餘額 |
| `ShortSaleYesterdayBalance` | bigint | 融券昨日餘額 |
| `ShortSaleLimit` | bigint | 融券限額 |
| `OffsetLoanAndShort` | bigint | 資券互抵 |
| `Note` | text | 備註 |

- **Unique Key**: `(stock_id, date)`
- **來源**: FinMind `taiwan_stock_margin_purchase_short_sale`

### `chip_short_sale` — 借券賣出餘額

| 欄位 | 型別 | 說明 |
|---|---|---|
| `stock_id` | text | 股票代碼 |
| `date` | date | 交易日期 |
| `MarginShortSalesPreviousDayBalance` | bigint | 融券前日餘額 |
| `MarginShortSalesShortSales` | bigint | 融券賣出 |
| `MarginShortSalesShortCovering` | bigint | 融券回補 |
| `MarginShortSalesStockRedemption` | bigint | 融券股票償還 |
| `MarginShortSalesCurrentDayBalance` | bigint | 融券今日餘額 |
| `MarginShortSalesQuota` | bigint | 融券限額 |
| `SBLShortSalesPreviousDayBalance` | bigint | 借券前日餘額 |
| `SBLShortSalesShortSales` | bigint | 借券賣出 |
| `SBLShortSalesReturns` | bigint | 借券歸還 |
| `SBLShortSalesAdjustments` | bigint | 借券調整 |
| `SBLShortSalesCurrentDayBalance` | bigint | 借券今日餘額 |
| `SBLShortSalesQuota` | bigint | 借券限額 |
| `SBLShortSalesShortCovering` | bigint | 借券回補 |

- **Unique Key**: `(stock_id, date)`
- **來源**: FinMind `taiwan_daily_short_sale_balances`

---

## 籌碼面 — 持股結構

### `chip_shareholding` — 外資持股

| 欄位 | 型別 | 說明 |
|---|---|---|
| `date` | date | 交易日期 |
| `stock_id` | text | 股票代碼 |
| `stock_name` | text | 股票名稱 |
| `InternationalCode` | text | ISIN 碼 |
| `ForeignInvestmentRemainingShares` | bigint | 外資尚可投資股數 |
| `ForeignInvestmentShares` | bigint | 外資持股數 |
| `ForeignInvestmentRemainRatio` | double precision | 外資尚可投資比率(%) |
| `ForeignInvestmentSharesRatio` | double precision | 外資持股比率(%) |
| `ForeignInvestmentUpperLimitRatio` | double precision | 外資投資上限比率(%) |
| `ChineseInvestmentUpperLimitRatio` | double precision | 陸資投資上限比率(%) |
| `NumberOfSharesIssued` | bigint | 發行股數 |
| `RecentlyDeclareDate` | text | 最近申報日 |
| `note` | text | 備註 |

- **Unique Key**: `(stock_id, date)`
- **來源**: FinMind `taiwan_stock_shareholding`

### `chip_holding_pct` — 持股分級表

| 欄位 | 型別 | 說明 |
|---|---|---|
| `date` | date | 交易日期 |
| `stock_id` | text | 股票代碼 |
| `HoldingSharesLevel` | text | 持股分級（共 17 級，如「1-999」「1,000-5,000」等） |
| `people` | bigint | 該級距人數 |
| `percent` | double precision | 該級距持股占比(%) |
| `unit` | bigint | 該級距持股股數 |

- **Unique Key**: `(stock_id, date, HoldingSharesLevel)`
- **來源**: FinMind `taiwan_stock_holding_shares_per`
- **備註**: 每支股票每天 17 筆（17 個持股級距），為全 DB 最大表

### `chip_securities_lending` — 借券成交明細

| 欄位 | 型別 | 說明 |
|---|---|---|
| `date` | date | 交易日期 |
| `stock_id` | text | 股票代碼 |
| `transaction_type` | text | 交易類型 |
| `volume` | bigint | 成交數量 |
| `fee_rate` | double precision | 費率(%) |
| `close` | double precision | 收盤價 |
| `original_return_date` | text | 原始歸還日 |
| `original_lending_period` | bigint | 原始借券天數 |

- **Unique Key**: `(stock_id, date, transaction_type)`
- **來源**: FinMind `taiwan_stock_securities_lending`

---

## 估值面

### `stock_per` — 本益比 / 股價淨值比 / 殖利率

| 欄位 | 型別 | 說明 |
|---|---|---|
| `date` | date | 交易日期 |
| `stock_id` | text | 股票代碼 |
| `dividend_yield` | double precision | 殖利率(%) |
| `PER` | double precision | 本益比 |
| `PBR` | double precision | 股價淨值比 |

- **Unique Key**: `(stock_id, date)`
- **來源**: FinMind `taiwan_stock_per_pbr`

### `market_value` — 市值

| 欄位 | 型別 | 說明 |
|---|---|---|
| `date` | date | 交易日期 |
| `stock_id` | text | 股票代碼 |
| `market_value` | bigint | 市值（元） |

- **Unique Key**: `(stock_id, date)`
- **來源**: FinMind `taiwan_stock_market_value`

### `month_revenue` — 月營收

| 欄位 | 型別 | 說明 |
|---|---|---|
| `date` | date | 營收公布日期 |
| `stock_id` | text | 股票代碼 |
| `country` | text | 國家（TW 或合併） |
| `revenue` | bigint | 營收金額（千元） |
| `revenue_month` | bigint | 營收月份 |
| `revenue_year` | bigint | 營收年份 |

- **Unique Key**: `(stock_id, date, country)`
- **來源**: FinMind `taiwan_stock_month_revenue`
- **備註**: FinMind API 不提供 `month_revenue_year_on_year`，YoY 由 `data_loader._compute_revenue_yoy()` 在查詢時動態計算

---

## 基本面

### `financial_reports` — 財務報表

| 欄位 | 型別 | 說明 |
|---|---|---|
| `date` | date | 季報日期（如 2025-03-31） |
| `stock_id` | text | 股票代碼 |
| `type` | text | 指標名稱（見下方 FOCUS_METRICS） |
| `value` | double precision | 指標數值 |

- **Unique Key**: `(stock_id, date, type)`
- **來源**: FinMind 損益表 + 資產負債表 + 現金流量表，篩選 FOCUS_METRICS
- **FOCUS_METRICS**: `Revenue`, `GrossProfit`, `OperatingIncome`, `NetIncome`, `EarningsPerShare`, `TotalAssets`, `TotalLiabilities`, `TotalEquity`, `CashFlowsFromOperatingActivities`, `CapitalExpenditure`
- **備註**: 長格式（每個指標一筆），需 pivot 為寬格式使用

### `dividend_history` — 股利紀錄

| 欄位 | 型別 | 說明 |
|---|---|---|
| `date` | date | 除息日 |
| `stock_id` | text | 股票代碼 |
| `dividend` | double precision | 每股股利（元） |

- **Unique Key**: `(stock_id, date, dividend)`
- **來源**: Yahoo Finance `yf.Ticker().dividends`

### `dividend_result` — 除權除息結果

| 欄位 | 型別 | 說明 |
|---|---|---|
| `date` | date | 除息日 |
| `stock_id` | text | 股票代碼 |
| `before_price` | double precision | 除息前收盤價 |
| `after_price` | double precision | 除息後開盤價 |
| `stock_and_cache_dividend` | double precision | 權息值（股票+現金股利） |
| `stock_or_cache_dividend` | text | 類型（權 or 息） |
| `max_price` | double precision | 除息日最高價 |
| `min_price` | double precision | 除息日最低價 |
| `open_price` | double precision | 除息日開盤價 |
| `reference_price` | double precision | 除息參考價 |

- **Unique Key**: `(stock_id, date)`（待建立）
- **來源**: FinMind `taiwan_stock_dividend_result`
- **用途**: 精確填息分析（填息天數、填息率）

---

## 交易行為

### `day_trading` — 當日沖銷交易

| 欄位 | 型別 | 說明 |
|---|---|---|
| `stock_id` | text | 股票代碼 |
| `date` | date | 交易日期 |
| `BuyAfterSale` | text | 可否先買後賣當沖（空字串 = 可） |
| `Volume` | bigint | 當沖成交量（股） |
| `BuyAmount` | bigint | 當沖買進金額（元） |
| `SellAmount` | bigint | 當沖賣出金額（元） |

- **Unique Key**: `(stock_id, date)`
- **來源**: FinMind `taiwan_stock_day_trading`
- **用途**: 計算當沖比例（`Volume / daily_price.volume`）作為散戶情緒指標

---

## 市場指標

### `total_return_index` — 含息報酬指數

| 欄位 | 型別 | 說明 |
|---|---|---|
| `price` | double precision | 報酬指數值 |
| `index_id` | text | 指數代碼（TAIEX = 加權指數） |
| `date` | date | 日期 |

- **Unique Key**: `(index_id, date)`（待建立）
- **來源**: FinMind `taiwan_stock_total_return_index`
- **用途**: 含息報酬基準比較，比 0050 更精確

### `stock_delisting` — 下市櫃紀錄

| 欄位 | 型別 | 說明 |
|---|---|---|
| `date` | date | 下市日期 |
| `stock_id` | text | 股票代碼 |
| `stock_name` | text | 股票名稱 |

- **Unique Key**: `(stock_id, date)`（待建立）
- **來源**: FinMind `taiwan_stock_delisting`
- **用途**: 回測時修正存活者偏差

---

## 參考資料

### `twstock_code` — 股票代碼元資料

| 欄位 | 型別 | 說明 |
|---|---|---|
| `商品類型` | text | 類型（股票/ETF/權證等） |
| `商品代號` | text | 股票代碼 |
| `商品名稱` | text | 股票名稱 |
| `ISINCode` | text | ISIN 國際證券代碼 |
| `上市日` | timestamp | 上市日期 |
| `市場別` | text | 市場（上市/上櫃） |
| `產業別` | text | 產業分類 |
| `CFICode` | text | CFI 分類碼（ESVUFR = 普通股） |

- **Unique Key**: `(商品代號)`
- **來源**: twstock 套件
- **備註**: 用 `CFICode = 'ESVUFR'` 篩選普通股，`商品類型 = 'ETF'` 篩選 ETF

### `securities_trader_info` — 券商基本資訊

| 欄位 | 型別 | 說明 |
|---|---|---|
| `securities_trader_id` | text | 券商代碼 |
| `securities_trader` | text | 券商名稱 |
| `date` | date | 開業日期 |
| `address` | text | 地址 |
| `phone` | text | 電話 |

- **Unique Key**: `(securities_trader_id)`（待建立）
- **來源**: FinMind `taiwan_securities_trader_info`
- **備註**: 靜態資料，共 991 家券商分點

---

## 系統表

### `recommendation_history` — 選股推薦追蹤

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | bigint | 自動遞增主鍵 |
| `report_date` | date | 報告日期 |
| `stock_id` | varchar | 股票代碼 |
| `stock_name` | varchar | 股票名稱 |
| `rank` | integer | 排名 |
| `total_score` | double precision | 總分 |
| `agree_count` | integer | 策略同意數 |
| `total_strategies` | integer | 總策略數 |
| `entry_price` | double precision | 進場價格 |
| `rsi` | double precision | RSI 指標值 |
| `week_return` | double precision | 週報酬率 |
| `avg_volume_20d` | double precision | 20 日均量 |
| `sector` | varchar | 產業大類 |
| `sub_industry` | varchar | 次產業 |
| `git_commit` | varchar | Git commit hash |
| `app_version` | varchar | 應用版本 |
| `strategy_votes` | jsonb | 各策略投票結果 |
| `strategy_hashes` | jsonb | 策略版本指紋 |
| `strategy_weights` | jsonb | 策略權重 |
| `picker_config` | jsonb | 選股器設定 |
| `price_t5` | double precision | T+5 價格 |
| `price_t10` | double precision | T+10 價格 |
| `price_t20` | double precision | T+20 價格 |
| `return_t5` | double precision | T+5 報酬率 |
| `return_t10` | double precision | T+10 報酬率 |
| `return_t20` | double precision | T+20 報酬率 |
| `created_at` | timestamptz | 建立時間 |

- **Unique Key**: `(report_date, stock_id)`
- **來源**: 系統產生（`daily_stock_picker.py` + `performance_tracker.py`）

### `scanner_run_log` — Scanner 執行日誌

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | bigint | 自動遞增主鍵 |
| `run_date` | date | 執行日期 |
| `scanner_name` | varchar | Scanner 名稱 |
| `started_at` | timestamptz | 開始時間 |
| `finished_at` | timestamptz | 結束時間 |
| `duration_sec` | double precision | 執行秒數 |
| `status` | varchar | 狀態（success/partial/failed） |
| `total_targets` | integer | 目標總數 |
| `success_count` | integer | 成功數 |
| `skip_count` | integer | 跳過數 |
| `fail_count` | integer | 失敗數 |
| `error_message` | text | 錯誤訊息 |
| `data_max_date` | date | 資料最新日期 |
| `triggered_by` | varchar | 觸發方式（manual/scheduler） |
| `created_at` | timestamptz | 建立時間 |

- **Unique Key**: `(run_date, scanner_name, started_at)`
- **來源**: 系統產生（`core/alert_manager.py`）

### `scan_progress` — 掃描進度（斷點續傳）

| 欄位 | 型別 | 說明 |
|---|---|---|
| `stock_id` | text | 股票代碼 |
| `table_name` | text | 資料表名稱 |
| `completed_at` | timestamp | 完成時間 |

- **Primary Key**: `(stock_id, table_name)`
- **來源**: 系統產生

---

## 重要規則

### 權證過濾

`save_to_db()` 會自動過濾 `stock_id` 長度 >= 6 碼的權證資料。所有寫入路徑統一生效，無需在各 scanner 中個別處理。白名單表（`twstock_code`、`total_return_index` 等無 stock_id 或靜態資料表）不受此過濾影響。

### 欄位命名慣例

- FinMind 原始欄位保留 PascalCase（如 `MarginPurchaseTodayBalance`、`HoldingSharesLevel`）
- 系統計算欄位使用 snake_case（如 `foreign_investors_buy`、`total_buy`）
- `daily_price` 的欄位已統一為小寫（`open/high/low/close/volume`）

### DB 連線注意事項

- 所有讀取必須使用 `safe_read_sql()`，禁止直接 `pd.read_sql()`
- Supabase 連線自動切換 session mode (port 5432)
- `save_to_db()` 含連線錯誤自動重試
