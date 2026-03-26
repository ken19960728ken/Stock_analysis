# Stock Analysis - 台灣股市量化交易系統

> 台灣股市全方位量化交易系統：自動撈取價格（日/週/月K）、籌碼、財報、估值等資料，儲存至 Supabase PostgreSQL，搭配 Streamlit 量化分析平台（26 個內建策略、12 個分析頁面）進行回測、因子分析、產業輪動、事件研究與機器學習選股。支援 Cloud Run 雙服務部署（Pipeline Job + Analysis Service）。

## 功能

### 資料撈取
- [x] 日 / 週 / 月 K 線價格資料撈取（Yahoo Finance）
- [x] 財務報表 + 股利資料撈取（FinMind + Yahoo Finance）
- [x] 籌碼面資料撈取（三大法人、融資融券、股權分散、持股比例、借券、借券賣出餘額）
- [x] 估值面資料撈取（月營收、PER/PBR/殖利率、市值）
- [x] 兩層產業分類撈取（sector + sub_industry，FinMind + HiStock）
- [x] 每日批量更新（FinMind 批量 API，7 次呼叫 < 1 分鐘）
- [x] 斷點續傳（中斷後重新執行自動跳過已完成股票）
- [x] 統一限速器（Token-aware delay + 429 自動重試 + 預算控制 + threading.Lock）
- [x] 統一日誌系統（RotatingFileHandler + console 輸出）
- [x] 本地 SQLite 索引，per-dataset 斷點續傳 + 失敗記錄

### 量化分析平台（Streamlit，12 個頁面）
- [x] 個股分析（K 線、技術指標、籌碼、基本面、同業比較，支援日/週/月K切換）
- [x] 多維度因子篩選選股
- [x] 26 個內建交易策略 + 績效報告
- [x] 配對交易（Engle-Granger 共整合 + Z-Score）
- [x] 風險管理（VaR、最大回撤、相關性矩陣）
- [x] 市場總覽（全市場漲跌、法人動向、估值分佈、FRED 經濟指標）
- [x] 多策略組合回測（4 種權重最佳化：等權/Sharpe最大化/最小波動率/風險平價）
- [x] 因子分析（IC 回測、因子相關性、有效性排行、動態權重追蹤）
- [x] 產業輪動模型（營收動能 + 法人流向 + 估值面 → 三因子產業排名 + 13 條供應鏈分析 + Granger 因果自動發現 + 指數衰減加權 + ICIR 動態權重）
- [x] 事件研究（除息/財報事件 CAR/AAR 分析 + 事件策略回測）
- [x] 機器學習選股（LightGBM + Walk-Forward 回測）
- [x] 報告瀏覽（Markdown 渲染 + CSV 表格 + 下載）

### 每日選股報告
- [x] 多策略投票 + 流動性過濾（11 個策略加權評分）
- [x] 同業百分位排名（PER、營收成長、法人買超）
- [x] 產業分佈摘要（雙層：sector → sub_industry）
- [x] Email 自動推送（Gmail SMTP + .md 附件）

### 雲端部署（GCP Cloud Run）
- [x] Pipeline Job（每日抓資料 + 選股報告，跑完自動停止）
- [x] Analysis Service（Streamlit 前端，按需 scale 0-2 instances）
- [x] Cloud Scheduler 自動排程（週一至五 18:30/18:40 UTC+8）
- [x] GCP Secret Manager 整合（敏感變數加密儲存）
- [x] 同一 repo + 兩個 Dockerfile + 不同 entrypoint

### 監控
- [x] Web 監控儀表板（FastAPI + Chart.js，即時追蹤撈取進度）

## 安裝

Python 版本建議為：`3.11`

### 取得專案

```bash
git clone https://github.com/ken19960728ken/Stock_analysis.git
cd Stock_analysis
```

### 安裝套件

本專案使用 [uv](https://docs.astral.sh/uv/) 作為套件管理工具（推薦）：

```bash
# 本地開發（安裝全部套件）
uv sync --extra all

# 只安裝 pipeline 相關（Docker pipeline 用）
uv sync --extra pipeline

# 只安裝 analysis 相關（Docker analysis 用）
uv sync --extra analysis
```

### 環境變數設定

在專案根目錄建立 `.env` 檔案：

```env
SUPABASE_URL=postgresql://user:password@host:port/dbname   # 必填
FINMIND_TOKEN=your_finmind_jwt_token                       # 選填，VIP 限額 6,000 次/小時（每小時重置），人為限速 1.5~2.5s/call
FRED_API_KEY=your_fred_api_key                             # 選填，市場總覽頁面的經濟指標
EMAIL_SENDER=you@gmail.com                                 # 選填，每日選股報告 Email 推送
EMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx                     # 選填，Gmail 應用程式密碼
EMAIL_RECIPIENTS=a@b.com,c@d.com                           # 選填，收件人（逗號分隔）
DB_POOL_SIZE=5                                             # 選填，連線池大小（Cloud Run 建議 3）
DB_POOL_OVERFLOW=3                                         # 選填，連線池溢出數（Cloud Run 建議 2）
```

## 使用方式

```bash
# === 資料撈取（統一入口，一律用 uv run python） ===
uv run python main.py --scanner price          # 日K價格資料（Yahoo Finance）
uv run python main.py --scanner price_weekly   # 週K價格資料（Yahoo Finance）
uv run python main.py --scanner price_monthly  # 月K價格資料（Yahoo Finance）
uv run python main.py --scanner fundamental    # 財務報表 + 股利
uv run python main.py --scanner chip           # 籌碼面（三大法人、融資融券等 6 項）
uv run python main.py --scanner valuation      # 月營收 + PER/PBR + 市值
uv run python main.py --scanner industry       # 產業分類（兩層：大類 + 次產業）
uv run python main.py --scanner all            # 依序執行全部 scanner

# === 每日更新（批量模式，< 1 分鐘） ===
uv run python main.py --daily                  # 手動執行今日更新（資料抓取 + 選股報告）
uv run python main.py --daily-data             # 僅資料抓取（價格 + 籌碼 + 估值面）
uv run python main.py --daily-report           # 僅選股報告 + Email 推送

# === 每日選股報告 ===
uv run python main.py --pick-stocks                         # 每日選股報告（Top 20）
uv run python main.py --pick-stocks --pick-date 2026-03-03   # 指定日期
uv run python main.py --pick-stocks --pick-top 10 --pick-days 7  # 自訂參數

# === 策略回測報告 ===
uv run python main.py --report                              # 列出所有策略
uv run python main.py --report "MA 交叉" --report-all       # 全市場回測報告
uv run python main.py --report "法人跟單" --report-stocks 2330 2317  # 指定股票

# === 量化分析平台 ===
uv run python main.py --analysis               # 啟動 Streamlit 分析平台 (http://localhost:8501)

# === 監控儀表板 ===
uv run python main.py --dashboard              # 啟動 Web 儀表板 (http://localhost:8050)

# === 工具指令 ===
uv run python main.py --usage                  # 查詢 FinMind API 使用量
uv run python main.py --init-index             # 從遠端 DB 初始化本地索引
uv run python main.py --show-failures          # 顯示失敗統計
uv run python main.py --reset-failures         # 清除全部失敗記錄
uv run python main.py --scanner chip --budget 50  # 限制 FinMind API 預算
```

### 雲端部署（GCP Cloud Run）

詳細步驟請參考 [`deploy/部署流程.md`](deploy/部署流程.md)。

```bash
# 快速部署（需先安裝 gcloud CLI + Docker）
source .env.deploy                    # 載入 GCP 專案設定
bash deploy/setup.sh                  # 初始化 GCP（只需一次）
bash deploy/setup-secrets.sh          # 建立 Secret Manager Secrets（只需一次）
bash deploy/deploy-pipeline.sh        # 部署 Pipeline Job
bash deploy/deploy-analysis.sh        # 部署 Analysis Service
bash deploy/setup-scheduler.sh        # 設定排程（只需一次）
```

### 運行測試

```bash
uv run pytest tests/ -v    # 952 個測試
```

## 專案架構

```
Stock_analysis/
├── main.py                        # 統一 CLI 入口
├── core/                          # 共用模組
│   ├── logger.py                  # 統一日誌（RotatingFileHandler）
│   ├── db.py                      # DB engine 單例、save_to_db、斷點續傳
│   ├── local_index.py             # 本地 SQLite 索引（斷點續傳 + 失敗記錄）
│   ├── finmind_client.py          # FinMind DataLoader 單例 + Token 管理
│   ├── rate_limiter.py            # 統一限速器（Token-aware + 429 重試 + 預算）
│   ├── stock_list.py              # 目標股票清單查詢
│   ├── scanner_base.py            # BaseScanner 抽象類別
│   ├── constants.py               # 全域常數 + 產業標準化
│   └── notifier.py                # Email 通知（Gmail SMTP）
├── scanners/                      # 資料撈取模組
│   ├── price_scanner.py           # 日K（Yahoo Finance）
│   ├── price_scanner_weekly.py    # 週K（Yahoo Finance）
│   ├── price_scanner_monthly.py   # 月K（Yahoo Finance）
│   ├── fundamental_scanner.py     # 財報 + 股利（FinMind + Yahoo）
│   ├── chip_scanner.py            # 籌碼面 6 項（FinMind）
│   ├── valuation_scanner.py       # 估值面 3 項（FinMind）
│   ├── industry_scanner.py        # 兩層產業分類（FinMind + JSON）
│   └── daily_updater.py           # 每日批量更新（< 1 分鐘）
├── analysis/                      # 量化分析平台（Streamlit）
│   ├── app.py                     # Streamlit 主入口
│   ├── pages/                     # 12 個分析頁面
│   │   ├── 1_個股分析.py          # K 線、指標、籌碼、基本面、同業比較
│   │   ├── 2_因子篩選.py          # 多維度條件過濾選股
│   │   ├── 3_策略回測.py          # 23 策略 + 績效報告
│   │   ├── 4_配對交易.py          # 共整合 + Z-Score
│   │   ├── 5_風險管理.py          # VaR、回撤、相關性
│   │   ├── 6_市場總覽.py          # 全市場漲跌、法人、估值
│   │   ├── 7_策略組合.py          # 多策略組合回測（4 種權重最佳化）
│   │   ├── 8_因子分析.py          # IC 回測、因子相關性、動態權重
│   │   ├── 9_產業輪動.py          # 營收動能 + 法人流向 + 估值面 + 供應鏈分析 + Granger 因果
│   │   ├── 10_事件分析.py         # 除息/財報事件 CAR/AAR
│   │   ├── 11_機器學習.py         # LightGBM 選股 + Walk-Forward
│   │   └── 12_報告瀏覽.py         # Markdown 渲染 + CSV 表格
│   ├── strategies/                # 26 個交易策略
│   │   ├── base.py                # Strategy ABC + BacktestResult
│   │   ├── ma_cross.py            # MA 交叉
│   │   ├── macd_signal.py         # MACD 訊號
│   │   ├── bollinger.py           # Bollinger 突破
│   │   ├── rsi_reversal.py        # RSI 反轉
│   │   ├── parabolic_sar.py       # Parabolic SAR
│   │   ├── heikin_ashi.py         # Heikin-Ashi
│   │   ├── dual_thrust.py         # Dual Thrust
│   │   ├── institutional.py       # 法人跟單
│   │   ├── margin_signal.py       # 融資融券訊號
│   │   ├── ownership_concentration.py  # 股權集中度
│   │   ├── value_investing.py     # 價值投資
│   │   ├── fundamental_ratio.py   # 財報三率
│   │   ├── free_cash_flow.py      # 自由現金流
│   │   ├── multi_factor.py        # 多因子綜合
│   │   ├── event_driven.py        # 事件驅動
│   │   ├── ml_factor.py           # 機器學習選股
│   │   ├── trend_filtered_ma.py   # 趨勢過濾MA
│   │   ├── adaptive_ensemble.py   # 多策略動態組合
│   │   ├── volume_price_momentum.py  # 量價動能
│   │   ├── revenue_momentum.py    # 營收動能
│   │   ├── volatility_squeeze.py  # 波動率壓縮突破
│   │   └── sub_industry_rotation.py  # 次產業輪動
│   └── utils/                     # 分析工具模組
│       ├── data_loader.py         # 統一 DB 查詢 + @st.cache_data
│       ├── indicators.py          # pandas/numpy 技術指標
│       ├── charts.py              # Plotly 圖表工廠
│       ├── backtester.py          # 回測引擎（台灣手續費/稅）
│       ├── portfolio_backtester.py # 多策略組合回測引擎
│       ├── portfolio_optimizer.py # 4 種組合最佳化方法
│       ├── factor_engine.py       # 多因子評分引擎 + 滾動 IC
│       ├── dynamic_weights.py     # 滾動 IC → 動態因子權重
│       ├── sector_rotation.py     # 產業輪動（營收動能 + 法人流向 + 估值面）
│       ├── event_study.py         # 事件研究引擎（CAR/AAR）
│       ├── ml_stock_picker.py     # LightGBM 選股引擎
│       ├── risk.py                # VaR, CVaR, Sharpe, Sortino, Beta
│       ├── pair_trading.py        # 共整合、Z-Score、半衰期
│       ├── peer_comparison.py     # 同業比較分析（百分位排名）
│       └── supply_chain.py        # 供應鏈連動分析（領先落後）
├── scripts/                       # 獨立工具腳本
│   ├── daily_stock_picker.py      # 每日選股報告（多策略投票）
│   ├── strategy_report.py         # 通用策略掃描回測報告
│   ├── value_investing_report.py  # 價值投資報告產生器
│   ├── db_add_constraints.py      # DB Unique Constraint 冪等腳本
│   └── scrape_sub_industry.py     # HiStock 次產業分類爬蟲
├── deploy/                        # 雲端部署
│   ├── setup.sh                   # GCP 專案初始化
│   ├── setup-secrets.sh           # Secret Manager Secrets 建立
│   ├── deploy-pipeline.sh         # 部署 Pipeline Job
│   ├── deploy-analysis.sh         # 部署 Analysis Service
│   ├── setup-scheduler.sh         # Cloud Scheduler 排程
│   └── 部署流程.md                # 完整部署文件
├── data/                          # 靜態資料
│   └── sub_industry_mapping.json  # 次產業對照表
├── dashboard/                     # 監控儀表板
│   ├── app.py                     # FastAPI 後端
│   └── static/index.html          # Chart.js 圓餅圖 + 狀態表格
├── Dockerfile.pipeline            # Cloud Run Job 映像
├── Dockerfile.analysis            # Cloud Run Service 映像
├── .dockerignore                  # Docker 排除清單
├── .streamlit/config.toml         # Streamlit 雲端配置
├── tests/                         # 測試套件（952 個測試）
├── pyproject.toml                 # 專案設定（uv, optional-dependencies）
└── .env                           # 環境變數（.gitignore）
```

## 交易策略

系統內建 26 個交易策略，涵蓋技術面、籌碼面、基本面、事件面、產業面與機器學習：

| 策略 | 類型 | 說明 |
|---|---|---|
| MA 交叉 | 技術面 | 均線黃金交叉 / 死亡交叉 |
| MACD 訊號 | 技術面 | MACD 柱狀圖翻正 / 翻負 |
| Bollinger 突破 | 技術面 | 布林通道突破與回歸 |
| RSI 反轉 | 技術面 | RSI 超買超賣反轉 |
| Parabolic SAR | 技術面 | 拋物線停損反轉 |
| Heikin-Ashi | 技術面 | 平均K線趨勢判斷 |
| Dual Thrust | 技術面 | 區間突破策略 |
| 趨勢過濾MA | 技術面 | MA 交叉 + MA200 趨勢過濾 + 回檔反彈 |
| 量價動能 | 技術面 | 放量突破 + OBV 資金流向 |
| 波動率壓縮突破 | 技術面 | BB+KC Squeeze 突破 |
| 法人跟單 | 籌碼面 | 跟隨三大法人買賣超 |
| 融資融券訊號 | 籌碼面 | 融資減少 + 股價上漲 |
| 股權集中度 | 籌碼面 | 大戶持股增加 + 股東人數減少 |
| 當沖情緒反轉 | 籌碼面 | 當沖比例 Z-Score 逆向交易 |
| 價值投資 | 基本面 | 低估值 + 高殖利率 |
| 財報三率 | 基本面 | 毛利率、營益率、淨利率 |
| 自由現金流 | 基本面 | 自由現金流正向成長 |
| 營收動能 | 基本面 | 營收 YoY 加速 + 營收新高 |
| 多因子綜合 | 混合 | 技術面(40%) + 籌碼面(30%) + 基本面(30%) |
| 多策略動態組合 | 混合 | 技術+籌碼+基本面 動態加權 |
| 事件驅動 | 事件面 | 除息/財報事件前買入、事件後賣出 |
| 次產業輪動 | 產業面 | 次產業營收動能 + 法人流向排名 |
| 機器學習選股 | ML 多因子 | LightGBM 多因子預測分位 + 選股 |

## 資料庫表格

| Table | 來源 | 內容 |
|---|---|---|
| `daily_price` | Yahoo Finance | 日K線 OHLCV |
| `weekly_price` | Yahoo Finance | 週K線 OHLCV |
| `monthly_price` | Yahoo Finance | 月K線 OHLCV |
| `financial_reports` | FinMind + Yahoo | 財務報表（損益表 + 資產負債表） |
| `dividend_history` | Yahoo Finance | 股利紀錄 |
| `twstock_code` | FinMind | 股票代碼元資料 |
| `chip_institutional` | FinMind | 三大法人買賣超 |
| `chip_margin` | FinMind | 融資融券 |
| `chip_shareholding` | FinMind | 股權分散表 |
| `chip_holding_pct` | FinMind | 持股比例 |
| `chip_securities_lending` | FinMind | 借券資料 |
| `chip_short_sale` | FinMind | 借券賣出餘額 |
| `month_revenue` | FinMind | 月營收 |
| `stock_per` | FinMind | 本益比 / 股價淨值比 / 殖利率 |
| `market_value` | FinMind | 市值 |
| `industry_classification` | FinMind + JSON | 兩層產業分類（sector + sub_industry） |
| `industry_mapping` | FinMind | 股票產業分類（舊表，向後相容） |

## 專案技術

- **語言** — Python 3.11
- **套件管理** — uv（optional-dependencies: pipeline / analysis / dashboard / all）
- **資料處理** — pandas, SQLAlchemy
- **資料來源** — FinMind, Yahoo Finance (yfinance), FRED API
- **資料庫** — Supabase PostgreSQL + 本地 SQLite 索引
- **分析平台** — Streamlit, Plotly
- **機器學習** — LightGBM, scikit-learn
- **統計分析** — statsmodels, scipy
- **監控儀表板** — FastAPI, Uvicorn, Chart.js
- **雲端部署** — GCP Cloud Run (Job + Service) + Cloud Scheduler + Artifact Registry + Secret Manager
- **容器化** — Docker（兩個 Dockerfile，amd64 交叉建置）
- **測試** — pytest（952 個測試）

## 第三方服務

- [Supabase](https://supabase.com/) — PostgreSQL 雲端資料庫
- [FinMind](https://finmindtrade.com/) — 台灣股市籌碼面 / 財報 / 估值 API
- [Yahoo Finance](https://finance.yahoo.com/) — 股價 / 股利資料
- [FRED](https://fred.stlouisfed.org/) — 美國經濟指標（選用）
- [GCP Cloud Run](https://cloud.google.com/run) — 容器化部署（選用）

## 聯絡作者

- [GitHub](https://github.com/ken19960728ken)
