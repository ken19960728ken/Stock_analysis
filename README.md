# Stock Analysis - 台灣股市量化交易系統

> 台灣股市量化交易系統，自動撈取價格、籌碼、財報、估值等資料，儲存至 Supabase PostgreSQL，供後續分析與策略回測使用。

## 功能

- [x] 日 K 線價格資料撈取（Yahoo Finance）
- [x] 財務報表 + 股利資料撈取（FinMind + Yahoo Finance）
- [x] 籌碼面資料撈取（三大法人、融資融券、股權分散、持股比例、借券、借券賣出餘額）
- [x] 估值面資料撈取（月營收、PER/PBR/殖利率、市值）
- [x] 斷點續傳（中斷後重新執行自動跳過已完成股票）
- [x] 統一限速器（Token-aware delay + 429 自動重試）
- [x] 統一日誌系統（RotatingFileHandler + console 輸出）
- [ ] 資料分析與量化策略
- [ ] 回測系統
- [ ] 實戰部署

## 安裝

以下將會引導你如何安裝此專案到你的電腦上。

Python 版本建議為：`3.11`

### 取得專案

```bash
git clone https://github.com/ken19960728ken/Stock_analysis.git
```

### 移動到專案內

```bash
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

在專案根目錄建立 `.env` 檔案，填入以下變數：

```env
SUPABASE_URL=postgresql://user:password@host:port/dbname
FINMIND_TOKEN=your_finmind_jwt_token  # 選填，有 Token 可提升 API 限速
```

### 運行專案

```bash
# 統一入口（推薦）
python main.py --scanner price          # 日K價格資料
python main.py --scanner fundamental    # 財務報表 + 股利
python main.py --scanner chip           # 籌碼面（6 項資料）
python main.py --scanner valuation      # 月營收 + PER/PBR + 市值
python main.py --scanner all            # 依序執行全部 scanner

# 單獨執行 scanner（支援 --test 單支測試）
python -m scanners.chip_scanner --test 2330
```

### 運行測試

```bash
uv run pytest tests/ -v
```

## 環境變數說明

```env
SUPABASE_URL=     # Supabase PostgreSQL 連線字串（必填）
FINMIND_TOKEN=    # FinMind API Token（選填，有 Token 限速 1.5~2.5s，無 Token 4~6s）
```

## 資料夾說明

```
Stock_analysis/
├── core/                       # 共用模組
│   ├── logger.py               # 統一日誌模組（RotatingFileHandler）
│   ├── db.py                   # DB 連線 engine 單例、save_to_db、斷點續傳
│   ├── finmind_client.py       # FinMind DataLoader 單例 + Token 管理
│   ├── rate_limiter.py         # 統一限速器（Token-aware delay + 429 重試）
│   ├── stock_list.py           # 目標股票清單查詢
│   └── scanner_base.py         # BaseScanner 抽象類別
├── scanners/                   # Scanner 模組
│   ├── price_scanner.py        # 日K價格（Yahoo Finance）
│   ├── fundamental_scanner.py  # 財報 + 股利（FinMind + Yahoo）
│   ├── chip_scanner.py         # 籌碼面（FinMind，6 個資料集）
│   └── valuation_scanner.py    # 估值面（FinMind，3 個資料集）
├── tests/                      # 測試套件（83 個測試）
├── logs/                       # 日誌目錄（.gitignore）
├── main.py                     # 統一入口
├── pyproject.toml              # 專案設定
└── requirements.txt            # Python 依賴清單
```

## 專案技術

- Python 3.11
- pandas 3.0.0
- SQLAlchemy 2.0.46
- FinMind 1.9.5
- yfinance 1.1.0
- tqdm 4.67.3
- psycopg2-binary 2.9.11
- pytest 9.0.2

## 第三方服務

- [Supabase](https://supabase.com/) — PostgreSQL 雲端資料庫
- [FinMind](https://finmindtrade.com/) — 台灣股市籌碼面 / 財報 / 估值 API
- [Yahoo Finance](https://finance.yahoo.com/) — 股價 / 股利資料

## 資料庫表格

| Table | 內容 |
|---|---|
| `daily_price` | OHLCV 日K線 |
| `financial_reports` | 財務報表（損益表 + 資產負債表） |
| `dividend_history` | 股利紀錄 |
| `twstock_code` | 股票代碼元資料 |
| `chip_institutional` | 三大法人買賣超 |
| `chip_margin` | 融資融券 |
| `chip_shareholding` | 股權分散表 |
| `chip_holding_pct` | 持股比例 |
| `chip_securities_lending` | 借券資料 |
| `chip_short_sale` | 借券賣出餘額 |
| `month_revenue` | 月營收 |
| `stock_per` | 本益比 / 股價淨值比 / 殖利率 |
| `market_value` | 市值 |

## 聯絡作者

- [GitHub](https://github.com/ken19960728ken)
