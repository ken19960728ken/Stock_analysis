# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

台灣股市量化交易系統，分為兩大部分：

1. **資料撈取**：撈取台灣股市商品信息、三年內價格資料、籌碼資料、財務報表，儲存至 Supabase PostgreSQL。
2. **分析與策略**：基於撈取的資料做資料整理分析、制定量化交易策略、編寫回測腳本，最終目標是實戰部署。

## AI 角色定位

Claude 在此專案中扮演**資深量化交易員**，熟悉全球金融市場，協助：資料撈取、資料清洗、建模分析、回測、實戰部署。

## Setup & Commands

```bash
# Install dependencies (uses uv package manager)
uv sync

# === 統一入口（推薦） ===
python main.py --scanner price          # 日K價格資料（Yahoo Finance）
python main.py --scanner fundamental    # 財務報表 + 股利
python main.py --scanner chip           # 籌碼面（三大法人、融資融券等 6 項）
python main.py --scanner valuation      # 月營收 + PER/PBR + 市值
python main.py --scanner all            # 依序執行全部 scanner

# === 單獨執行 scanner（支援 --test 單支測試） ===
python -m scanners.price_scanner                 # 全市場日K
python -m scanners.fundamental_scanner            # 財報 + 股利
python -m scanners.chip_scanner                   # 籌碼面
python -m scanners.chip_scanner --test 2330       # 測試單支
python -m scanners.valuation_scanner              # 估值面

# === 舊腳本（保留但不再主要使用） ===
python script.py                 # 基礎 OHLCV（固定清單）
python db_market_scanner.py      # 全市場掃描（已重構至 scanners/price_scanner.py）
python fundamental_scanner.py    # 財報（已重構至 scanners/fundamental_scanner.py）
python get_financial_report.py   # 股利+EPS（已合併至 scanners/fundamental_scanner.py）
python append_stock_codes.py     # 初始化商品代碼至 SQLite
python nn_predict.py             # PyTorch 價格預測模型
```

No test suite exists. No linter is configured.

## Architecture

**Data flow**: External APIs → Python scripts → Supabase PostgreSQL (+ local SQLite for stock codes)

### 共用模組 `core/`

| Module | Description |
|---|---|
| `core/db.py` | DB 連線 engine 單例、`save_to_db()`、`check_exists()` 斷點續傳 |
| `core/finmind_client.py` | FinMind DataLoader 單例 + Token 管理 |
| `core/rate_limiter.py` | 統一限速器（Token-aware delay + 429 重試） |
| `core/stock_list.py` | 目標股票清單查詢（DB 優先 + fallback） |
| `core/scanner_base.py` | BaseScanner 抽象類別（主迴圈、tqdm、Ctrl+C、斷點續傳） |

### Scanner 模組 `scanners/`

| Scanner | Source | DB Tables |
|---|---|---|
| `price_scanner.py` | Yahoo Finance | `daily_price` |
| `fundamental_scanner.py` | FinMind + Yahoo | `financial_reports`, `dividend_history` |
| `chip_scanner.py` | FinMind | `chip_institutional`, `chip_margin`, `chip_shareholding`, `chip_holding_pct`, `chip_securities_lending`, `chip_short_sale` |
| `valuation_scanner.py` | FinMind | `month_revenue`, `stock_per`, `market_value` |

### Part 2: 分析、策略與回測

- **`nn_predict.py`** — PyTorch 3 層 MLP (12→24→12→1)，以半導體股歷史資料訓練。特徵：OHLC、漲跌幅、5/10/20 日均線、動量、K 線型態。含線性回歸基準模型。
- 量化策略與回測腳本持續開發中。

### Database Tables (Supabase)

| Table | Content |
|---|---|
| `daily_price` | OHLCV history per stock |
| `financial_reports` | EPS, revenue, and other financial metrics |
| `dividend_history` | Dividend records |
| `twstock_code` | Stock metadata (code, name, market, CFI) |
| `chip_institutional` | 三大法人買賣超 |
| `chip_margin` | 融資融券 |
| `chip_shareholding` | 股權分散表 |
| `chip_holding_pct` | 持股比例 |
| `chip_securities_lending` | 借券資料 |
| `chip_short_sale` | 借券賣出餘額 |
| `month_revenue` | 月營收 |
| `stock_per` | 本益比/股價淨值比/殖利率 |
| `market_value` | 市值 |

### Configuration

- **`.env`** — Must contain `SUPABASE_URL` (PostgreSQL connection string). Optionally `FINMIND_TOKEN` (JWT for higher API rate limits).
- **`configs/constants.py`** — DB connection string template (placeholder, actual connection uses `.env`).
- **Python 3.11** required (`.python-version` and `pyproject.toml`).

## Key Patterns

- All DB writes use SQLAlchemy with `if_exists="append"` via pandas `to_sql`.
- All scanners inherit from `BaseScanner`，提供 tqdm 進度條、Ctrl+C 安全中斷、斷點續傳、結算報告。
- Stock codes are converted between internal format (e.g. `2330`) and Yahoo format (`2330.TW` for listed, `.TWO` for OTC).
- `RateLimiter` 統一管理 API 限速：FinMind 有 Token 1.5-2.5s / 無 Token 4-6s / Yahoo 0.8-1.5s，含 429 自動重試。
- DB engine 和 FinMind DataLoader 均為單例模式，避免重複初始化。
