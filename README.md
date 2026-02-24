# Stock Analysis - 台灣股市量化交易系統

> 台灣股市全方位量化交易系統：自動撈取價格（日/週/月K）、籌碼、財報、估值等資料，儲存至 Supabase PostgreSQL，搭配 Streamlit 量化分析平台（14 個內建策略）進行回測與風險管理。

## 功能

### 資料撈取
- [x] 日 / 週 / 月 K 線價格資料撈取（Yahoo Finance）
- [x] 財務報表 + 股利資料撈取（FinMind + Yahoo Finance）
- [x] 籌碼面資料撈取（三大法人、融資融券、股權分散、持股比例、借券、借券賣出餘額）
- [x] 估值面資料撈取（月營收、PER/PBR/殖利率、市值）
- [x] 每日批量更新（FinMind 批量 API，7 次呼叫 < 1 分鐘）
- [x] 斷點續傳（中斷後重新執行自動跳過已完成股票）
- [x] 統一限速器（Token-aware delay + 429 自動重試 + 預算控制）
- [x] 統一日誌系統（RotatingFileHandler + console 輸出）
- [x] 本地 SQLite 索引，per-dataset 斷點續傳 + 失敗記錄

### 量化分析平台（Streamlit）
- [x] 個股分析（K 線、技術指標、籌碼、基本面）
- [x] 多維度因子篩選選股
- [x] 14 個內建交易策略 + 績效報告
- [x] 多策略組合回測
- [x] 配對交易（Engle-Granger 共整合 + Z-Score）
- [x] 風險管理（VaR、最大回撤、相關性矩陣）
- [x] 市場總覽（全市場漲跌、法人動向、估值分佈）

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

本專案使用 [uv](https://docs.astral.sh/uv/) 作為套件管理工具（推薦），也支援 pip：

```bash
# 使用 uv（推薦）
uv sync

# 或使用 pip
pip install -r requirements.txt
```

### 環境變數設定

在專案根目錄建立 `.env` 檔案：

```env
SUPABASE_URL=postgresql://user:password@host:port/dbname   # 必填
FINMIND_TOKEN=your_finmind_jwt_token                       # 選填，有 Token 限速 1.5~2.5s，無 Token 4~6s
FRED_API_KEY=your_fred_api_key                             # 選填，市場總覽頁面的經濟指標
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
uv run python main.py --scanner all            # 依序執行全部 scanner

# === 每日更新（批量模式，< 1 分鐘） ===
uv run python main.py --daily                  # 手動執行今日更新（價格 + 籌碼）
uv run python main.py --daily-schedule         # 常駐排程：每天 17:00 UTC+8 自動更新

# === 量化分析平台 ===
uv run python main.py --analysis               # 啟動 Streamlit 分析平台 (http://localhost:8501)

# === 監控儀表板 ===
uv run python main.py --dashboard              # 啟動 Web 儀表板 (http://localhost:8050)

# === 工具指令 ===
uv run python main.py --usage                  # 查詢 FinMind API 使用量
uv run python main.py --init-index             # 從遠端 DB 初始化本地索引
uv run python main.py --schedule               # 排程模式：每小時自動循環
uv run python main.py --show-failures          # 顯示失敗統計
uv run python main.py --reset-failures         # 清除全部失敗記錄
uv run python main.py --scanner chip --budget 50  # 限制 FinMind API 預算

# === 單獨執行 scanner（支援 --test 單支測試） ===
uv run python -m scanners.price_scanner                 # 全市場日K
uv run python -m scanners.price_scanner_weekly           # 全市場週K
uv run python -m scanners.price_scanner_monthly          # 全市場月K
uv run python -m scanners.fundamental_scanner            # 財報 + 股利
uv run python -m scanners.chip_scanner                   # 籌碼面
uv run python -m scanners.chip_scanner --test 2330       # 測試單支
uv run python -m scanners.valuation_scanner              # 估值面
```

### 運行測試

```bash
uv run pytest tests/ -v
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
│   └── scanner_base.py            # BaseScanner 抽象類別
├── scanners/                      # 資料撈取模組
│   ├── price_scanner.py           # 日K（Yahoo Finance）
│   ├── price_scanner_weekly.py    # 週K（Yahoo Finance）
│   ├── price_scanner_monthly.py   # 月K（Yahoo Finance）
│   ├── fundamental_scanner.py     # 財報 + 股利（FinMind + Yahoo）
│   ├── chip_scanner.py            # 籌碼面 6 項（FinMind）
│   ├── valuation_scanner.py       # 估值面 3 項（FinMind）
│   └── daily_updater.py           # 每日批量更新（< 1 分鐘）
├── analysis/                      # 量化分析平台（Streamlit）
│   ├── app.py                     # Streamlit 主入口
│   ├── pages/                     # 7 個分析頁面
│   │   ├── 1_個股分析.py          # K 線、指標、籌碼、基本面
│   │   ├── 2_因子篩選.py          # 多維度條件過濾選股
│   │   ├── 3_策略回測.py          # 14 策略 + 績效報告
│   │   ├── 4_配對交易.py          # 共整合 + Z-Score
│   │   ├── 5_風險管理.py          # VaR、回撤、相關性
│   │   ├── 6_市場總覽.py          # 全市場漲跌、法人、估值
│   │   └── 7_策略組合.py          # 多策略組合回測
│   ├── strategies/                # 14 個交易策略
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
│   │   └── multi_factor.py        # 多因子綜合
│   └── utils/                     # 分析工具模組
│       ├── data_loader.py         # 統一 DB 查詢 + @st.cache_data
│       ├── indicators.py          # pandas/numpy 技術指標
│       ├── charts.py              # Plotly 圖表工廠
│       ├── backtester.py          # 回測引擎（台灣手續費/稅）
│       ├── portfolio_backtester.py # 多策略組合回測引擎
│       ├── factor_engine.py       # 多因子評分引擎
│       ├── risk.py                # VaR, CVaR, Sharpe, Sortino, Beta
│       └── pair_trading.py        # 共整合、Z-Score、半衰期
├── dashboard/                     # 監控儀表板
│   ├── app.py                     # FastAPI 後端
│   └── static/index.html          # Chart.js 圓餅圖 + 狀態表格
├── scripts/                       # 獨立工具腳本
│   └── value_investing_report.py  # 價值投資報告產生器
├── docs/                          # 文件
│   └── 選股策略藍圖.md            # 選股策略藍圖
├── tests/                         # 測試套件（169+ 測試）
│   ├── conftest.py                # pytest fixtures
│   ├── test_price_scanner.py
│   ├── test_fundamental_scanner.py
│   ├── test_chip_scanner.py
│   ├── test_valuation_scanner.py
│   ├── test_daily_updater.py
│   ├── test_strategies.py
│   ├── test_backtester.py
│   ├── test_portfolio_backtester.py
│   ├── test_factor_engine.py
│   └── test_finmind_api_diagnostic.py
├── logs/                          # 日誌目錄（.gitignore）
├── pyproject.toml                 # 專案設定（uv）
├── requirements.txt               # pip 依賴清單
└── .env                           # 環境變數（.gitignore）
```

## 交易策略

系統內建 14 個交易策略，涵蓋技術面、籌碼面、基本面三大維度：

| 策略 | 類型 | 說明 |
|---|---|---|
| MA 交叉 | 技術面 | 均線黃金交叉 / 死亡交叉 |
| MACD 訊號 | 技術面 | MACD 柱狀圖翻正 / 翻負 |
| Bollinger 突破 | 技術面 | 布林通道突破與回歸 |
| RSI 反轉 | 技術面 | RSI 超買超賣反轉 |
| Parabolic SAR | 技術面 | 拋物線停損反轉 |
| Heikin-Ashi | 技術面 | 平均K線趨勢判斷 |
| Dual Thrust | 技術面 | 區間突破策略 |
| 法人跟單 | 籌碼面 | 跟隨三大法人買賣超 |
| 融資融券訊號 | 籌碼面 | 融資減少 + 股價上漲 |
| 股權集中度 | 籌碼面 | 大戶持股增加 + 股東人數減少 |
| 價值投資 | 基本面 | 低估值 + 高殖利率 |
| 財報三率 | 基本面 | 毛利率、營益率、淨利率 |
| 自由現金流 | 基本面 | 自由現金流正向成長 |
| 多因子綜合 | 混合 | 技術面(40%) + 籌碼面(30%) + 基本面(30%) |

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

## 專案技術

- **語言** — Python 3.11
- **套件管理** — uv
- **資料處理** — pandas, SQLAlchemy
- **資料來源** — FinMind, Yahoo Finance (yfinance), FRED API
- **資料庫** — Supabase PostgreSQL + 本地 SQLite 索引
- **分析平台** — Streamlit, Plotly
- **監控儀表板** — FastAPI, Uvicorn, Chart.js
- **統計分析** — statsmodels, scipy
- **測試** — pytest（169+ 測試）

## 第三方服務

- [Supabase](https://supabase.com/) — PostgreSQL 雲端資料庫
- [FinMind](https://finmindtrade.com/) — 台灣股市籌碼面 / 財報 / 估值 API
- [Yahoo Finance](https://finance.yahoo.com/) — 股價 / 股利資料
- [FRED](https://fred.stlouisfed.org/) — 美國經濟指標（選用）

## 聯絡作者

- [GitHub](https://github.com/ken19960728ken)
