# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

台灣股市量化交易系統，分為兩大部分：

1. **資料撈取**：撈取台灣股市商品信息、三年內價格資料（日/週/月K）、籌碼資料、財務報表，儲存至 Supabase PostgreSQL。
2. **分析與策略**：基於撈取的資料做資料整理分析、制定量化交易策略（16 個內建策略）、回測引擎、風險管理，最終目標是實戰部署。

## AI 角色定位

Claude 在此專案中扮演**資深量化交易員**，熟悉全球金融市場，協助：資料撈取、資料清洗、建模分析、回測、實戰部署。

## Setup & Commands

```bash
# Install dependencies (uses uv package manager)
uv sync --extra all            # 本地開發（安裝全部套件）
# uv sync --extra pipeline     # 只安裝 pipeline 相關（Docker pipeline 用）
# uv sync --extra analysis     # 只安裝 analysis 相關（Docker analysis 用）

# === 統一入口（推薦，一律用 uv run python） ===
uv run python main.py --scanner price          # 日K價格資料（Yahoo Finance）
uv run python main.py --scanner price_weekly   # 週K價格資料（Yahoo Finance）
uv run python main.py --scanner price_monthly  # 月K價格資料（Yahoo Finance）
uv run python main.py --scanner fundamental    # 財務報表 + 股利
uv run python main.py --scanner chip           # 籌碼面（三大法人、融資融券等 6 項）
uv run python main.py --scanner valuation      # 月營收 + PER/PBR + 市值
uv run python main.py --scanner industry       # 產業分類（FinMind taiwan_stock_info）
uv run python main.py --scanner all            # 依序執行全部 scanner

# === 每日更新（批量模式，< 1 分鐘） ===
uv run python main.py --daily                  # 手動執行今日更新（價格 + 籌碼）
uv run python main.py --daily-schedule         # 常駐排程：每天 17:00 UTC+8 自動更新 + 選股報告

# === 工具指令 ===
uv run python main.py --analysis               # 啟動量化分析平台 (http://localhost:8501)
uv run python main.py --dashboard              # 啟動監控儀表板 (http://localhost:8050)
uv run python main.py --usage                  # 查詢 FinMind API 使用量
uv run python main.py --init-index             # 從遠端 DB 初始化本地索引
uv run python main.py --schedule               # 排程模式：每小時自動循環
uv run python main.py --show-failures          # 顯示各 dataset 失敗統計
uv run python main.py --reset-failures         # 清除全部失敗記錄
uv run python main.py --scanner chip --budget 50  # 限制 FinMind API 預算

# === 每日選股報告 ===
uv run python main.py --pick-stocks                         # 每日選股報告（Top 20，自動取 DB 最新日期）
uv run python main.py --pick-stocks --pick-date 2026-03-03   # 指定日期的選股報告
uv run python main.py --pick-stocks --pick-top 10 --pick-days 7  # 自訂參數
uv run python scripts/daily_stock_picker.py                  # 直接執行
uv run python scripts/daily_stock_picker.py --date 2026-03-03 --top 10  # 指定日期 + Top N
uv run python scripts/daily_stock_picker.py --top 10 --days 7 --output reports/

# === 策略回測報告 ===
uv run python main.py --report                              # 列出所有策略
uv run python main.py --report "MA 交叉" --report-all       # 全市場 MA 交叉回測報告
uv run python main.py --report "法人跟單" --report-stocks 2330 2317  # 指定股票
uv run python main.py --report "RSI 反轉" --report-all --report-top 10 --report-years 3
uv run python scripts/strategy_report.py --list              # 直接執行：列出策略
uv run python scripts/strategy_report.py --strategy "MA 交叉" --stocks 2330 2317
uv run python scripts/strategy_report.py --strategy "MA 交叉" --all --top 20 --no-html
uv run python scripts/strategy_report.py --strategy "MA 交叉" --stocks 2330 --param fast_period=10

# === 單獨執行 scanner（支援 --test 單支測試） ===
uv run python -m scanners.price_scanner                 # 全市場日K
uv run python -m scanners.price_scanner_weekly           # 全市場週K
uv run python -m scanners.price_scanner_monthly          # 全市場月K
uv run python -m scanners.fundamental_scanner            # 財報 + 股利
uv run python -m scanners.chip_scanner                   # 籌碼面
uv run python -m scanners.chip_scanner --test 2330       # 測試單支
uv run python -m scanners.valuation_scanner              # 估值面
uv run python -m scanners.industry_scanner               # 產業分類（兩層：大類 + 次產業）
```

Run tests: `uv run pytest tests/ -v`. No linter is configured.

**Important**: 本專案使用 uv 管理 Python 環境，所有 Python 指令必須使用 `uv run python` 執行。

## Architecture

**Data flow**: External APIs → Python scripts → Supabase PostgreSQL → Streamlit 分析平台

### 共用模組 `core/`

| Module | Description |
|---|---|
| `core/logger.py` | 統一日誌模組（`setup_logger()`、RotatingFileHandler） |
| `core/db.py` | DB 連線 engine 單例、`safe_read_sql()`（防殭屍連線）、`save_to_db()`（含連線錯誤重試）、`check_exists()` 斷點續傳、自動切換 Supabase session mode |
| `core/local_index.py` | 本地 SQLite 索引（`scan_index.db`），per-dataset 斷點續傳 + 失敗記錄 |
| `core/finmind_client.py` | FinMind DataLoader 單例 + Token 管理 |
| `core/rate_limiter.py` | 統一限速器（Token-aware delay + 429 重試 + 預算控制） |
| `core/stock_list.py` | 目標股票清單查詢（DB 優先 + fallback） |
| `core/scanner_base.py` | BaseScanner 抽象類別（主迴圈、tqdm、Ctrl+C、斷點續傳） |
| `core/constants.py` | 全域常數（`TRADING_DAYS_PER_YEAR=252`、`RISK_FREE_RATE=0.015`、`TWSE_SECTORS`、`INDUSTRY_ALIAS_MAP`、`normalize_sector()`） |
| `core/notifier.py` | Email 通知模組（Gmail SMTP + HTTP CONNECT proxy，`send_report_email()`） |

### 量化分析平台 `analysis/`

| Module | Description |
|---|---|
| `analysis/app.py` | Streamlit 主入口 |
| `analysis/pages/1_個股分析.py` | K 線、技術指標、籌碼、基本面、同業比較 |
| `analysis/pages/2_因子篩選.py` | 多維度條件過濾選股 |
| `analysis/pages/3_策略回測.py` | 16 個內建策略 + 績效報告 |
| `analysis/pages/4_配對交易.py` | Engle-Granger 共整合 + Z-Score |
| `analysis/pages/5_風險管理.py` | VaR、回撤、相關性矩陣 |
| `analysis/pages/6_市場總覽.py` | 全市場漲跌、法人、產業熱力圖、估值分佈 |
| `analysis/pages/7_策略組合.py` | 多策略組合回測（4 種權重最佳化） |
| `analysis/pages/8_因子分析.py` | IC 回測、因子相關性、有效性排行、動態權重 |
| `analysis/pages/9_產業輪動.py` | 營收動能 + 法人流向 → 產業排名 + 供應鏈分析 |
| `analysis/pages/10_事件分析.py` | 除息/財報事件研究 + CAR/AAR |
| `analysis/pages/11_機器學習.py` | LightGBM 選股 + Walk-Forward 回測 |
| `analysis/pages/12_報告瀏覽.py` | 瀏覽 reports/ 報告（Markdown 渲染 + CSV 表格 + 下載） |
| `analysis/strategies/` | 22 個策略 (Strategy Pattern)，見下方策略清單 |
| `analysis/utils/data_loader.py` | 統一 DB 查詢 + `@st.cache_data` |
| `analysis/utils/indicators.py` | 純 pandas/numpy 技術指標 |
| `analysis/utils/charts.py` | Plotly 圖表工廠 |
| `analysis/utils/backtester.py` | 回測引擎（含台灣手續費/稅） |
| `analysis/utils/portfolio_backtester.py` | 多策略組合回測引擎 |
| `analysis/utils/portfolio_optimizer.py` | 4 種組合最佳化（Max Sharpe/Min Vol/Risk Parity/BL） |
| `analysis/utils/factor_engine.py` | 多因子評分引擎 + 滾動 IC |
| `analysis/utils/dynamic_weights.py` | 滾動 IC → 動態因子權重 |
| `analysis/utils/sector_rotation.py` | 產業輪動（營收動能 + 法人流向，支援 sector/sub_industry 兩層） |
| `analysis/utils/event_study.py` | 事件研究引擎（CAR/AAR） |
| `analysis/utils/ml_stock_picker.py` | LightGBM 選股引擎 |
| `analysis/utils/risk.py` | VaR, CVaR, Sharpe, Sortino, Beta, 風險貢獻 |
| `analysis/utils/pair_trading.py` | 共整合、Z-Score、半衰期 |
| `analysis/utils/peer_comparison.py` | 同業比較分析（同業查詢、指標比較、百分位排名） |
| `analysis/utils/supply_chain.py` | 產業供應鏈連動分析（營收動能傳導、領先落後） |

#### 策略清單（22 個）

| 策略名稱 | Class | 類型 |
|---|---|---|
| MA 交叉 | `MACrossStrategy` | 技術面 |
| MACD 訊號 | `MACDStrategy` | 技術面 |
| Bollinger 突破 | `BollingerStrategy` | 技術面 |
| RSI 反轉 | `RSIReversalStrategy` | 技術面 |
| Parabolic SAR | `ParabolicSARStrategy` | 技術面 |
| Heikin-Ashi | `HeikinAshiStrategy` | 技術面 |
| Dual Thrust | `DualThrustStrategy` | 技術面 |
| 法人跟單 | `InstitutionalStrategy` | 籌碼面 |
| 融資融券訊號 | `MarginSignalStrategy` | 籌碼面 |
| 股權集中度 | `OwnershipConcentrationStrategy` | 籌碼面 |
| 價值投資 | `ValueInvestingStrategy` | 基本面 |
| 財報三率 | `FundamentalRatioStrategy` | 基本面 |
| 自由現金流 | `FreeCashFlowStrategy` | 基本面 |
| 多因子綜合 | `MultiFactorStrategy` | 技術面(40%)+籌碼面(30%)+基本面(30%) |
| 事件驅動 | `EventDrivenStrategy` | 事件面 |
| 機器學習選股 | `MLFactorStrategy` | ML 多因子 |
| 趨勢過濾MA | `TrendFilteredMAStrategy` | 技術面（MA 交叉 + MA200 趨勢過濾 + 回檔反彈） |
| 多策略動態組合 | `AdaptiveEnsembleStrategy` | 技術面+籌碼面+基本面 動態加權 |
| 量價動能 | `VolumePriceMomentumStrategy` | 技術面（放量突破 + OBV 資金流向） |
| 營收動能 | `RevenueMomentumStrategy` | 基本面（營收 YoY 加速 + 營收新高） |
| 波動率壓縮突破 | `VolatilitySqueezeStrategy` | 技術面（BB+KC Squeeze 突破） |
| 次產業輪動 | `SubIndustryRotationStrategy` | 產業面（次產業營收動能+法人流向排名） |

### 部署 `deploy/`

| File | Description |
|---|---|
| `Dockerfile.pipeline` | Cloud Run Job 映像（scanners + scripts + strategies） |
| `Dockerfile.analysis` | Cloud Run Service 映像（Streamlit 分析平台） |
| `.dockerignore` | Docker 建置排除清單 |
| `.streamlit/config.toml` | Streamlit 雲端配置（headless, 0.0.0.0:8501） |
| `deploy/setup.sh` | GCP 專案初始化（啟用 API + Artifact Registry） |
| `deploy/deploy-pipeline.sh` | 建置 + 部署 Pipeline Job（amd64 交叉建置） |
| `deploy/deploy-analysis.sh` | 建置 + 部署 Analysis Service（amd64 交叉建置） |
| `deploy/setup-scheduler.sh` | Cloud Scheduler 排程（週一至五 17:00 UTC+8） |
| `deploy/部署流程.md` | 完整部署文件（含環境版本 + 踩坑紀錄） |

### Dashboard 模組 `dashboard/`

| Module | Description |
|---|---|
| `dashboard/app.py` | FastAPI 後端：4 個端點（`/`、`/api/stats`、`/api/stocks`、`/api/failures`） |
| `dashboard/static/index.html` | 單頁儀表板（Chart.js 圓餅圖 + 商品矩陣 + 失敗記錄） |

### 靜態資料 `data/`

| File | Description |
|---|---|
| `sub_industry_mapping.json` | 次產業對照表（sector → sub_industry → stock_ids） |

### 腳本 `scripts/`

| Script | Description |
|---|---|
| `value_investing_report.py` | 價值投資全市場回測報告（專用） |
| `strategy_report.py` | 通用策略掃描回測報告（22 策略 + 0050 基準比較） |
| `daily_stock_picker.py` | 每日選股報告（多策略投票 + 流動性過濾，支援 `--date` 指定日期） |
| `db_add_constraints.py` | DB Unique Constraint 冪等腳本（DB 重建後執行） |
| `db_integrity_check.py` | DB 完整性掃描（交易日清單、每日記錄數、重複偵測、跨表一致性） |
| `backfill_missing_data.py` | 一次性資料補抓（stock_per/market_value 批量 + DailyUpdater 補缺漏） |
| `test_email.py` | Cloud Run Email 寄送測試（stderr 輸出，用於 Cloud Logging 驗證） |
| `scrape_sub_industry.py` | 從 HiStock 爬取次產業分類 → `data/sub_industry_mapping.json`（一次性工具，`--diff` 比較差異） |

### Scanner 模組 `scanners/`

| Scanner | Source | DB Tables |
|---|---|---|
| `price_scanner.py` | Yahoo Finance | `daily_price` |
| `price_scanner_weekly.py` | Yahoo Finance | `weekly_price` |
| `price_scanner_monthly.py` | Yahoo Finance | `monthly_price` |
| `fundamental_scanner.py` | FinMind + Yahoo | `financial_reports`, `dividend_history` |
| `chip_scanner.py` | FinMind | `chip_institutional`, `chip_margin`, `chip_shareholding`, `chip_holding_pct`, `chip_securities_lending`, `chip_short_sale` |
| `valuation_scanner.py` | FinMind | `month_revenue`, `stock_per`, `market_value` |
| `industry_scanner.py` | FinMind + JSON | `industry_classification`, `industry_mapping` |
| `daily_updater.py` | FinMind (批量) | `daily_price` + 6 個 chip 表 |

### Database Tables (Supabase)

| Table | Content | Unique Key |
|---|---|---|
| `daily_price` | 日K線 OHLCV | `(stock_id, date)` |
| `weekly_price` | 週K線 OHLCV | `(stock_id, date)` |
| `monthly_price` | 月K線 OHLCV | `(stock_id, date)` |
| `financial_reports` | 財務報表（EPS、營收等） | `(stock_id, date, type)` |
| `dividend_history` | 股利紀錄 | `(stock_id, date, dividend)` |
| `twstock_code` | 股票代碼元資料（代號、名稱、市場、CFI） | `(商品代號)` |
| `chip_institutional` | 三大法人買賣超 | `(stock_id, date)` |
| `chip_margin` | 融資融券 | `(stock_id, date)` |
| `chip_shareholding` | 股權分散表 | `(stock_id, date)` |
| `chip_holding_pct` | 持股比例 | `(stock_id, date, HoldingSharesLevel)` |
| `chip_securities_lending` | 借券資料 | `(stock_id, date, transaction_type)` |
| `chip_short_sale` | 借券賣出餘額 | `(stock_id, date)` |
| `month_revenue` | 月營收 | `(stock_id, date, country)` |
| `stock_per` | 本益比/股價淨值比/殖利率 | `(stock_id, date)` |
| `market_value` | 市值 | `(stock_id, date)` |
| `industry_mapping` | 股票產業分類（舊表，向後相容） | — |
| `industry_classification` | 兩層產業分類（sector + sub_industry） | `(stock_id)` |

### Tests `tests/`

| Test File | Coverage |
|---|---|
| `test_price_scanner.py` | PriceScanner 單元測試 |
| `test_fundamental_scanner.py` | FundamentalScanner 單元測試 |
| `test_chip_scanner.py` | ChipScanner 單元測試 |
| `test_valuation_scanner.py` | ValuationScanner 單元測試 |
| `test_daily_updater.py` | DailyUpdater 測試（21 項） |
| `test_all_strategies.py` | 12 個策略獨立單元測試（54 項） |
| `test_strategies.py` | 4 個策略深度測試 + 整合驗證（30 項） |
| `test_backtester.py` | 回測引擎測試 |
| `test_portfolio_backtester.py` | 組合回測測試 |
| `test_portfolio_optimizer.py` | 組合最佳化測試（Max Sharpe/Min Vol/Risk Parity/BL） |
| `test_factor_engine.py` | 因子引擎測試 |
| `test_dynamic_weights.py` | 動態權重測試 |
| `test_sector_rotation.py` | 產業輪動測試 |
| `test_event_study.py` | 事件研究測試 |
| `test_ml_stock_picker.py` | ML 選股測試 |
| `test_indicators.py` | 技術指標模組測試（11 個指標函數） |
| `test_risk.py` | 風險指標模組測試（VaR/Sharpe/Beta/回撤等） |
| `test_pair_trading.py` | 配對交易測試（共整合/Z-Score/半衰期） |
| `test_data_loader.py` | 資料查詢層測試（Mock DB） |
| `test_charts.py` | Plotly 圖表工廠測試 |
| `test_core_constants.py` | core/constants.py 常數驗證 |
| `test_core_logger.py` | core/logger.py 日誌模組測試 |
| `test_core_db.py` | core/db.py 白名單驗證 + save/check + 連線重試測試 |
| `test_core_stock_list.py` | core/stock_list.py 股票清單測試 |
| `test_core_finmind_client.py` | core/finmind_client.py 單例 + Token 測試 |
| `test_core_rate_limiter.py` | core/rate_limiter.py 限速器 + 預算測試 |
| `test_core_local_index.py` | core/local_index.py SQLite 索引測試 |
| `test_core_scanner_base.py` | core/scanner_base.py 掃描流程 + 熔斷測試 |
| `test_strategy_report.py` | 通用策略回測報告測試（24 項） |
| `test_new_strategies.py` | 趨勢過濾MA + 多策略動態組合 測試（26 項） |
| `test_improved_strategies.py` | 策略強化測試（RSI 趨勢過濾、MACD 背離、法人拆分、券資比軋空，20 項） |
| `test_daily_stock_picker.py` | 每日選股報告測試（15 項） |
| `test_notifier.py` | Email 通知模組測試（16 項：寄送流程 + Markdown→HTML + 表格轉換） |
| `test_new_three_strategies.py` | 量價動能 + 營收動能 + 波動率壓縮突破 測試（23 項） |
| `test_industry_classification.py` | 兩層產業分類測試（26 項：標準化、Scanner、集中度、中性化、輪動兩層） |
| `test_peer_comparison.py` | 同業比較分析測試（get_peers、指標計算、百分位排名） |
| `test_sub_industry_rotation.py` | 次產業輪動策略測試（訊號生成、最大持有天數、參數邊界） |
| `test_supply_chain.py` | 供應鏈分析測試（營收動能、領先落後矩陣） |
| `test_finmind_api_diagnostic.py` | FinMind API 診斷（需 `-m api`） |

### Configuration

- **`.env`** — Must contain `SUPABASE_URL` (PostgreSQL connection string). Optionally `FINMIND_TOKEN` (JWT for higher API rate limits). Optionally `FRED_API_KEY` (FRED API key for economic indicators on 市場總覽 page; get one at https://fred.stlouisfed.org/docs/api/api_key.html). Email 通知需設定 `EMAIL_SENDER`、`EMAIL_APP_PASSWORD`（Gmail 應用程式密碼）、`EMAIL_RECIPIENTS`（逗號分隔多收件人）。若需透過代理連線 SMTP 可設 `EMAIL_PROXY`（如 `http://127.0.0.1:7890`）。
- **Python 3.11** required (`.python-version` and `pyproject.toml`).
- **`pyproject.toml` optional-dependencies** — `pipeline`（finmind/yfinance/tqdm/twstock）、`analysis`（streamlit/fredapi）、`dashboard`（fastapi/uvicorn）、`all`（全部）。本地開發用 `uv sync --extra all`，Docker 各自安裝對應 extra。
- **`DB_POOL_SIZE`** / **`DB_POOL_OVERFLOW`** — 可選環境變數，控制 SQLAlchemy 連線池大小（預設 5/3，Cloud Run 建議 3/2）。
- **`LOCAL_INDEX_PATH`** — 可選環境變數，覆寫本地 SQLite 索引路徑（預設 `scan_index.db`）。

## Key Patterns

- All DB writes use SQLAlchemy with `if_exists="append"` via pandas `to_sql`.
- All scanners inherit from `BaseScanner`，提供 tqdm 進度條、Ctrl+C 安全中斷、斷點續傳、結算報告。
- All strategies inherit from `Strategy` ABC（`analysis/strategies/base.py`），實作 `generate_signals(df, **params) -> pd.DataFrame`。
- Stock codes are converted between internal format (e.g. `2330`) and Yahoo format (`2330.TW` for listed, `.TWO` for OTC).
- 需要遍歷全市場股票時，應從 `twstock_code` 查詢（按 `商品類型` 過濾），不要從 `daily_price` 做 DISTINCT（含 4.7 萬筆權證）。
- `RateLimiter` 統一管理 API 限速：FinMind 有 Token 1.5-2.5s / 無 Token 4-6s / Yahoo 0.8-1.5s，含 429 自動重試。
- DB engine 和 FinMind DataLoader 均為單例模式，避免重複初始化。
- Supabase 連線自動偵測 Supavisor transaction mode (port 6543) 並切換為 session mode (port 5432)，避免 ~60 秒連線超時。`save_to_db()` 含連線錯誤自動重試。
- **所有 DB 讀取必須使用 `safe_read_sql(sql, params=)`**（`core/db.py`），禁止直接 `pd.read_sql(sql, engine)`。後者在 SQLAlchemy 2.x 下不會歸還連線，導致 `idle in transaction` 殭屍連線佔滿連線池。
- 所有資料表皆有 Unique Index，確保 `INSERT ... ON CONFLICT DO NOTHING` 正確跳過重複資料。DB 重建後需執行 `uv run python scripts/db_add_constraints.py` 重建約束。
- 每日排程 (`--daily-schedule`) 17:00 UTC+8 自動執行：Step 1 DailyUpdater 抓資料 → Step 2 `run_daily_pick()` 產出選股報告 → Step 3 `send_report_email()` Email 推送（含 .md 附件，環境變數缺失時靜默跳過）。報告日期預設取 DB 中 `MAX(date) FROM daily_price`，可用 `--pick-date` / `--date` 指定歷史日期（會自動加 `end_date` 過濾避免未來資料洩漏）。
- **macOS 休眠會暫停 `time.sleep()` 計時器**，導致 `--daily-schedule` 排程延遲或漏觸發。排程未觸發時需手動 kill 舊進程並重啟，再用 `--daily` + `--pick-stocks` 補跑。
- `--pick-stocks` 單獨執行只產報告不寄信；寄信邏輯僅在 `--daily-schedule` 的 Step 3。手動補產報告後需另外呼叫 `send_report_email()` 寄送。

## Logging

- 統一使用 `core/logger.py` 的 `setup_logger(name)` 取得 logger，禁止直接 `print()`。
- 正式環境日誌寫入 `logs/scanner.log`（RotatingFileHandler, 5MB x 3 備份）+ console (stderr)。
- 測試環境日誌寫入 `logs/test.log`，由 `tests/conftest.py` 的 session-scoped fixture 自動配置，與正式環境隔離。
- 日誌格式：`[2025-01-01 12:00:00] [INFO] [module_name] 訊息`
- `logs/` 目錄已加入 `.gitignore`。

## Workflow Conventions

- 執行重大操作（如切換功能、部署）前，先 git commit 並 push 當前改動。
- 修改 `main.py` 或 `core/` 模組後，需手動重啟 `--daily-schedule` 常駐進程（`kill` 舊進程 + `nohup uv run python main.py --daily-schedule` 重啟），否則不會載入新程式碼。
- 測試時使用多元股票代碼（含歷史失敗的股票），不要只用 2330 作為測試樣本。
- 完成重大功能變更後，主動提議更新 CLAUDE.md 與 README.md。
- Supabase SQL Editor 執行 `ALTER TABLE` 時不能加 `public.` schema 前綴（直接用 `ALTER TABLE table_name ...`）。
- 測試中避免硬編碼策略數量（如 `assert len(STRATEGY_MAP) == 22`），新增策略時需全域搜尋並更新所有相關斷言。

## Cloud Run 部署注意事項

- Apple Silicon Mac 部署到 Cloud Run 必須用 `docker buildx build --platform linux/amd64`，否則容器啟動會報 `exec format error`。
- gcloud `--set-env-vars` 遇到含 `@` 或特殊字元的值會解析失敗，應改用 `--env-vars-file` 搭配 YAML 檔傳入環境變數。
- macOS 13 (Ventura) 需安裝 Docker Desktop 4.30（build 149282），4.64+ 不支援 Ventura。
- gcloud CLI 在 macOS 13 需設定 `CLOUDSDK_PYTHON=/opt/homebrew/opt/python@3.10/libexec/bin/python3`，Homebrew 直接安裝會因 Python 版本衝突失敗。
