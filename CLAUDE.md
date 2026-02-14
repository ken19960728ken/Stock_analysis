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

# === 統一入口（推薦，一律用 uv run python） ===
uv run python main.py --scanner price          # 日K價格資料（Yahoo Finance）
uv run python main.py --scanner fundamental    # 財務報表 + 股利
uv run python main.py --scanner chip           # 籌碼面（三大法人、融資融券等 6 項）
uv run python main.py --scanner valuation      # 月營收 + PER/PBR + 市值
uv run python main.py --scanner all            # 依序執行全部 scanner

# === 工具指令 ===
uv run python main.py --dashboard              # 啟動監控儀表板 (http://localhost:8050)
uv run python main.py --usage                  # 查詢 FinMind API 使用量
uv run python main.py --init-index             # 從遠端 DB 初始化本地索引
uv run python main.py --schedule               # 排程模式：每小時自動循環
uv run python main.py --show-failures          # 顯示各 dataset 失敗統計
uv run python main.py --reset-failures         # 清除全部失敗記錄
uv run python main.py --scanner chip --budget 50  # 限制 FinMind API 預算

# === 單獨執行 scanner（支援 --test 單支測試） ===
uv run python -m scanners.price_scanner                 # 全市場日K
uv run python -m scanners.fundamental_scanner            # 財報 + 股利
uv run python -m scanners.chip_scanner                   # 籌碼面
uv run python -m scanners.chip_scanner --test 2330       # 測試單支
uv run python -m scanners.valuation_scanner              # 估值面
```

Run tests: `uv run pytest tests/ -v`. No linter is configured.

**Important**: 本專案使用 uv 管理 Python 環境，所有 Python 指令必須使用 `uv run python` 執行。

## Architecture

**Data flow**: External APIs → Python scripts → Supabase PostgreSQL

### 共用模組 `core/`

| Module | Description |
|---|---|
| `core/logger.py` | 統一日誌模組（`setup_logger()`、RotatingFileHandler） |
| `core/db.py` | DB 連線 engine 單例、`save_to_db()`、`check_exists()` 斷點續傳 |
| `core/local_index.py` | 本地 SQLite 索引（`scan_index.db`），per-dataset 斷點續傳 + 失敗記錄 |
| `core/finmind_client.py` | FinMind DataLoader 單例 + Token 管理 |
| `core/rate_limiter.py` | 統一限速器（Token-aware delay + 429 重試 + 預算控制） |
| `core/stock_list.py` | 目標股票清單查詢（DB 優先 + fallback） |
| `core/scanner_base.py` | BaseScanner 抽象類別（主迴圈、tqdm、Ctrl+C、斷點續傳） |

### Dashboard 模組 `dashboard/`

| Module | Description |
|---|---|
| `dashboard/app.py` | FastAPI 後端：4 個端點（`/`、`/api/stats`、`/api/stocks`、`/api/failures`） |
| `dashboard/static/index.html` | 單頁儀表板（Chart.js 圓餅圖 + 商品矩陣 + 失敗記錄） |

### Scanner 模組 `scanners/`

| Scanner | Source | DB Tables |
|---|---|---|
| `price_scanner.py` | Yahoo Finance | `daily_price` |
| `fundamental_scanner.py` | FinMind + Yahoo | `financial_reports`, `dividend_history` |
| `chip_scanner.py` | FinMind | `chip_institutional`, `chip_margin`, `chip_shareholding`, `chip_holding_pct`, `chip_securities_lending`, `chip_short_sale` |
| `valuation_scanner.py` | FinMind | `month_revenue`, `stock_per`, `market_value` |

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
- **Python 3.11** required (`.python-version` and `pyproject.toml`).

## Key Patterns

- All DB writes use SQLAlchemy with `if_exists="append"` via pandas `to_sql`.
- All scanners inherit from `BaseScanner`，提供 tqdm 進度條、Ctrl+C 安全中斷、斷點續傳、結算報告。
- Stock codes are converted between internal format (e.g. `2330`) and Yahoo format (`2330.TW` for listed, `.TWO` for OTC).
- `RateLimiter` 統一管理 API 限速：FinMind 有 Token 1.5-2.5s / 無 Token 4-6s / Yahoo 0.8-1.5s，含 429 自動重試。
- DB engine 和 FinMind DataLoader 均為單例模式，避免重複初始化。

## Logging

- 統一使用 `core/logger.py` 的 `setup_logger(name)` 取得 logger，禁止直接 `print()`。
- 正式環境日誌寫入 `logs/scanner.log`（RotatingFileHandler, 5MB x 3 備份）+ console (stderr)。
- 測試環境日誌寫入 `logs/test.log`，由 `tests/conftest.py` 的 session-scoped fixture 自動配置，與正式環境隔離。
- 日誌格式：`[2025-01-01 12:00:00] [INFO] [module_name] 訊息`
- `logs/` 目錄已加入 `.gitignore`。
