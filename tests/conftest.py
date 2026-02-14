"""
Shared test fixtures and configuration for Taiwan stock scanner tests.
Provides mock data and utilities for testing all scanner modules.
"""

import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# ============================================================================
# Sample Data for Stock 2330 (TSMC)
# ============================================================================

@pytest.fixture
def sample_stock_id():
    """Primary test stock: 2330 (TSMC)"""
    return "2330"


@pytest.fixture
def sample_stock_dict(sample_stock_id):
    """Stock dict with Yahoo symbol for 2330"""
    return {
        "stock_id": sample_stock_id,
        "yahoo_symbol": "2330.TW",
        "name": "台灣積電",
        "type": "股票",
    }


@pytest.fixture
def sample_price_data(sample_stock_id):
    """Realistic OHLCV data for TSMC (2330)"""
    dates = pd.date_range(start="2023-01-01", periods=10, freq="D")
    return pd.DataFrame({
        "date": dates,
        "stock_id": sample_stock_id,
        "open": [585.0, 586.0, 587.0, 588.0, 589.0, 590.0, 589.0, 588.0, 587.0, 586.0],
        "high": [590.0, 591.0, 592.0, 593.0, 594.0, 595.0, 594.0, 593.0, 592.0, 591.0],
        "low": [580.0, 581.0, 582.0, 583.0, 584.0, 585.0, 584.0, 583.0, 582.0, 581.0],
        "close": [585.0, 586.0, 587.0, 588.0, 589.0, 590.0, 589.0, 588.0, 587.0, 586.0],
        "volume": [30000000, 32000000, 28000000, 35000000, 31000000, 29000000, 33000000, 30000000, 32000000, 31000000],
    })


@pytest.fixture
def sample_chip_institutional_data(sample_stock_id):
    """Mock data for institutional investors (三大法人)"""
    dates = pd.date_range(start="2023-01-01", periods=5, freq="D")
    return pd.DataFrame({
        "date": dates,
        "stock_id": sample_stock_id,
        "foreign_investors_buy": [100000, 120000, 150000, 110000, 130000],
        "foreign_investors_sell": [80000, 90000, 100000, 95000, 110000],
        "investment_trust_buy": [50000, 55000, 60000, 52000, 58000],
        "investment_trust_sell": [45000, 48000, 52000, 50000, 55000],
        "dealer_buy": [30000, 35000, 40000, 32000, 38000],
        "dealer_sell": [28000, 32000, 38000, 30000, 36000],
    })


@pytest.fixture
def sample_chip_margin_data(sample_stock_id):
    """Mock data for margin purchase/short sale (融資融券)"""
    dates = pd.date_range(start="2023-01-01", periods=5, freq="D")
    return pd.DataFrame({
        "date": dates,
        "stock_id": sample_stock_id,
        "margin_purchase_balance": [10000, 12000, 11000, 13000, 12000],
        "short_sale_balance": [5000, 6000, 5500, 7000, 6500],
    })


@pytest.fixture
def sample_chip_shareholding_data(sample_stock_id):
    """Mock data for shareholding distribution (股權分散)"""
    return pd.DataFrame({
        "date": [datetime.date(2023, 1, 15)],
        "stock_id": sample_stock_id,
        "shareholding_range": ["1000001~5000000"],
        "shareholder_count": [5000],
        "holding_percentage": [25.5],
    })


@pytest.fixture
def sample_valuation_revenue_data(sample_stock_id):
    """Mock data for monthly revenue (月營收)"""
    dates = pd.date_range(start="2023-01-01", periods=6, freq="MS")
    return pd.DataFrame({
        "date": dates,
        "stock_id": sample_stock_id,
        "revenue": [150000000, 155000000, 160000000, 158000000, 162000000, 165000000],
        "month_revenue_year_on_year": [10.5, 12.3, 14.2, 13.5, 15.1, 16.2],
    })


@pytest.fixture
def sample_valuation_per_data(sample_stock_id):
    """Mock data for P/E, P/B, dividend yield (本益比/股價淨值比/殖利率)"""
    dates = pd.date_range(start="2023-01-01", periods=5, freq="D")
    return pd.DataFrame({
        "date": dates,
        "stock_id": sample_stock_id,
        "per": [18.5, 18.8, 19.2, 19.0, 18.9],
        "pbr": [2.5, 2.6, 2.7, 2.65, 2.62],
        "dividend_yield": [4.2, 4.1, 4.0, 4.05, 4.08],
    })


@pytest.fixture
def sample_valuation_market_value_data(sample_stock_id):
    """Mock data for market value (市值)"""
    dates = pd.date_range(start="2023-01-01", periods=5, freq="D")
    return pd.DataFrame({
        "date": dates,
        "stock_id": sample_stock_id,
        "market_value": [17000000000, 17200000000, 17400000000, 17300000000, 17500000000],
        "market_value_per_share": [580.0, 585.0, 590.0, 588.0, 595.0],
    })


@pytest.fixture
def sample_financial_statements_data(sample_stock_id):
    """Mock data for financial statements (損益表 + 資產負債表)"""
    return pd.DataFrame({
        "date": [
            datetime.date(2023, 3, 31),
            datetime.date(2023, 6, 30),
            datetime.date(2023, 9, 30),
            datetime.date(2023, 12, 31),
        ],
        "stock_id": sample_stock_id,
        "type": ["Revenue", "NetIncome", "TotalAssets", "TotalEquity"],
        "value": [450000000000, 150000000000, 2000000000000, 1200000000000],
    })


@pytest.fixture
def sample_dividend_history_data(sample_stock_id):
    """Mock data for dividend history"""
    return pd.DataFrame({
        "date": [
            datetime.date(2022, 1, 15),
            datetime.date(2022, 7, 15),
            datetime.date(2023, 1, 15),
            datetime.date(2023, 7, 15),
        ],
        "stock_id": sample_stock_id,
        "dividend": [10.0, 6.0, 11.0, 6.5],
    })


# ============================================================================
# Mock Engine and Database Functions
# ============================================================================

@pytest.fixture
def mock_engine():
    """Mock SQLAlchemy engine"""
    engine = MagicMock()
    engine.connect.return_value.__enter__ = MagicMock()
    engine.connect.return_value.__exit__ = MagicMock(return_value=None)
    return engine


@pytest.fixture
def mock_db_save(monkeypatch):
    """Mock db.save_to_db to always return True"""
    mock_fn = MagicMock(return_value=True)
    monkeypatch.setattr("core.db.save_to_db", mock_fn)
    # Also patch where scanners import it
    monkeypatch.setattr("scanners.chip_scanner.save_to_db", mock_fn)
    monkeypatch.setattr("scanners.valuation_scanner.save_to_db", mock_fn)
    monkeypatch.setattr("scanners.price_scanner.save_to_db", mock_fn)
    monkeypatch.setattr("scanners.fundamental_scanner.save_to_db", mock_fn)
    return mock_fn


@pytest.fixture
def mock_db_check_exists(monkeypatch):
    """Mock db.check_exists to always return False (no skip)"""
    mock_fn = MagicMock(return_value=False)
    monkeypatch.setattr("core.db.check_exists", mock_fn)
    return mock_fn


@pytest.fixture
def mock_db_get_engine(monkeypatch, mock_engine):
    """Mock db.get_engine"""
    monkeypatch.setattr("core.db.get_engine", MagicMock(return_value=mock_engine))


@pytest.fixture
def mock_db_dispose_engine(monkeypatch):
    """Mock db.dispose_engine"""
    mock_fn = MagicMock()
    monkeypatch.setattr("core.db.dispose_engine", mock_fn)
    return mock_fn


# ============================================================================
# Mock FinMind Client
# ============================================================================

@pytest.fixture
def mock_fm_loader():
    """Mock FinMind DataLoader"""
    loader = MagicMock()
    loader.taiwan_stock_institutional_investors = MagicMock(return_value=None)
    loader.taiwan_stock_margin_purchase_short_sale = MagicMock(return_value=None)
    loader.taiwan_stock_shareholding = MagicMock(return_value=None)
    loader.taiwan_stock_holding_shares_per = MagicMock(return_value=None)
    loader.taiwan_stock_securities_lending = MagicMock(return_value=None)
    loader.taiwan_stock_daily_short_sale_balances = MagicMock(return_value=None)
    loader.taiwan_stock_month_revenue = MagicMock(return_value=None)
    loader.taiwan_stock_per = MagicMock(return_value=None)
    loader.taiwan_stock_market_value = MagicMock(return_value=None)
    loader.taiwan_stock_financial_statement = MagicMock(return_value=None)
    loader.taiwan_stock_balance_sheet = MagicMock(return_value=None)
    return loader


@pytest.fixture
def mock_finmind_client(monkeypatch, mock_fm_loader):
    """Mock finmind_client.get_fm_loader and get_fm_token"""
    # Patch at the core module level
    monkeypatch.setattr(
        "core.finmind_client.get_fm_loader",
        lambda: mock_fm_loader,
    )
    monkeypatch.setattr(
        "core.finmind_client.get_fm_token",
        lambda: "test-token",
    )
    # Also patch where scanners import it
    monkeypatch.setattr(
        "scanners.chip_scanner.get_fm_loader",
        lambda: mock_fm_loader,
    )
    monkeypatch.setattr(
        "scanners.chip_scanner.get_fm_token",
        lambda: "test-token",
    )
    monkeypatch.setattr(
        "scanners.valuation_scanner.get_fm_loader",
        lambda: mock_fm_loader,
    )
    monkeypatch.setattr(
        "scanners.valuation_scanner.get_fm_token",
        lambda: "test-token",
    )
    monkeypatch.setattr(
        "scanners.fundamental_scanner.get_fm_loader",
        lambda: mock_fm_loader,
    )
    monkeypatch.setattr(
        "scanners.fundamental_scanner.get_fm_token",
        lambda: "test-token",
    )
    return mock_fm_loader


# ============================================================================
# Mock Rate Limiter
# ============================================================================

@pytest.fixture
def mock_rate_limiter(monkeypatch):
    """Mock RateLimiter to avoid actual delays"""

    class MockRateLimiter:
        """Mock rate limiter that doesn't actually wait"""
        def __init__(self, source="finmind"):
            self.source = source
            self.wait = MagicMock(side_effect=None)
            self.backoff = MagicMock(side_effect=None)

        def call_with_retry(self, fn, max_retries=3):
            """Execute fn without retry logic"""
            try:
                return fn()
            except Exception:
                return None

    monkeypatch.setattr(
        "core.rate_limiter.RateLimiter",
        MockRateLimiter,
    )
    # Also patch where scanners import it
    monkeypatch.setattr(
        "scanners.chip_scanner.RateLimiter",
        MockRateLimiter,
    )
    monkeypatch.setattr(
        "scanners.valuation_scanner.RateLimiter",
        MockRateLimiter,
    )
    monkeypatch.setattr(
        "scanners.price_scanner.RateLimiter",
        MockRateLimiter,
    )
    monkeypatch.setattr(
        "scanners.fundamental_scanner.RateLimiter",
        MockRateLimiter,
    )


# ============================================================================
# Mock Yahoo Finance
# ============================================================================

@pytest.fixture
def mock_yfinance(monkeypatch):
    """Mock yfinance.download and yfinance.Ticker"""
    def mock_download(ticker, period="3y", progress=False, auto_adjust=False):
        """Return mock OHLCV data"""
        dates = pd.date_range(end="2023-12-31", periods=100, freq="D")
        data = pd.DataFrame({
            "Date": dates,
            "Open": [580.0 + i * 0.5 for i in range(100)],
            "High": [590.0 + i * 0.5 for i in range(100)],
            "Low": [570.0 + i * 0.5 for i in range(100)],
            "Close": [585.0 + i * 0.5 for i in range(100)],
            "Adj Close": [585.0 + i * 0.5 for i in range(100)],
            "Volume": [30000000 + i * 100000 for i in range(100)],
        })
        data.set_index("Date", inplace=True)
        return data

    mock_yf = MagicMock()
    mock_yf.download = mock_download

    def mock_ticker_class(ticker):
        """Return mock Ticker object"""
        ticker_obj = MagicMock()
        dates = pd.date_range(end="2023-12-31", periods=10, freq="MS")
        ticker_obj.dividends = pd.Series(
            [10.0, 6.0, 11.0, 6.5, 10.5, 6.2, 11.2, 6.8, 10.2, 6.5],
            index=dates,
        )
        return ticker_obj

    mock_yf.Ticker = mock_ticker_class

    monkeypatch.setattr("scanners.price_scanner.yf", mock_yf)
    monkeypatch.setattr("scanners.fundamental_scanner.yf", mock_yf)
    return mock_yf


# ============================================================================
# Mock Stock List Functions
# ============================================================================

@pytest.fixture
def mock_stock_list(monkeypatch, sample_stock_id):
    """Mock stock_list.get_all_stocks and get_stock_ids_from_daily_price"""
    def mock_get_all_stocks():
        return [
            {
                "stock_id": sample_stock_id,
                "yahoo_symbol": "2330.TW",
                "name": "台灣積電",
                "type": "股票",
            }
        ]

    def mock_get_stock_ids():
        return [sample_stock_id]

    monkeypatch.setattr(
        "core.stock_list.get_all_stocks",
        mock_get_all_stocks,
    )
    monkeypatch.setattr(
        "core.stock_list.get_stock_ids_from_daily_price",
        mock_get_stock_ids,
    )


# ============================================================================
# Composite Fixtures for Common Setup
# ============================================================================

@pytest.fixture
def setup_scanner_mocks(
    mock_db_save,
    mock_db_check_exists,
    mock_db_dispose_engine,
    mock_finmind_client,
    mock_rate_limiter,
    mock_yfinance,
    mock_stock_list,
):
    """Setup all necessary mocks for scanner tests"""
    return {
        "save_to_db": mock_db_save,
        "check_exists": mock_db_check_exists,
        "dispose_engine": mock_db_dispose_engine,
    }
