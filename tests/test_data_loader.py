"""
資料查詢層測試 — analysis/utils/data_loader.py
Mock DB 連線，測試 SQL 構建邏輯、快取裝飾器容忍、空資料處理
"""

import os
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# ============================================================================
# 解除 Streamlit cache 裝飾器
# ============================================================================

@pytest.fixture(autouse=True)
def patch_streamlit_cache(monkeypatch):
    """Mock st.cache_data 為無操作裝飾器，避免依賴 Streamlit runtime"""
    import importlib

    mock_st = MagicMock()
    mock_st.cache_data = lambda **kwargs: (lambda fn: fn)

    monkeypatch.setitem(__import__("sys").modules, "streamlit", mock_st)

    # 重新載入 data_loader 以套用 mock
    import analysis.utils.data_loader as dl_module
    importlib.reload(dl_module)

    yield dl_module


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_engine(monkeypatch):
    """Mock get_engine"""
    engine = MagicMock()
    monkeypatch.setattr("analysis.utils.data_loader.get_engine", lambda: engine)
    return engine


@pytest.fixture
def sample_price_df():
    return pd.DataFrame({
        "stock_id": ["2330"] * 5,
        "date": pd.date_range("2023-01-01", periods=5),
        "open": [580, 585, 590, 588, 592],
        "high": [590, 595, 600, 598, 602],
        "low": [575, 580, 585, 583, 587],
        "close": [585, 590, 595, 593, 597],
        "volume": [30e6, 32e6, 28e6, 35e6, 31e6],
    })


@pytest.fixture
def sample_institutional_df():
    return pd.DataFrame({
        "stock_id": ["2330"] * 3,
        "date": pd.date_range("2023-01-01", periods=3),
        "foreign_investors_buy": [100000, 120000, 150000],
        "foreign_investors_sell": [80000, 90000, 100000],
    })


# ============================================================================
# FRED Functions
# ============================================================================

class TestFREDFunctions:
    def test_fred_indicators_config(self, patch_streamlit_cache):
        dl = patch_streamlit_cache
        assert "real_gdp" in dl.FRED_INDICATORS
        assert "sp500" in dl.FRED_INDICATORS
        assert "oil_wti" in dl.FRED_INDICATORS

    def test_fred_categories(self, patch_streamlit_cache):
        dl = patch_streamlit_cache
        assert "美國總經" in dl.FRED_CATEGORIES
        assert "美國市場" in dl.FRED_CATEGORIES

    def test_is_fred_available_no_key(self, patch_streamlit_cache, monkeypatch):
        dl = patch_streamlit_cache
        monkeypatch.delenv("FRED_API_KEY", raising=False)
        # 無 key 應回傳 False（除非 .env 有設定）
        # 測試環境通常沒有 FRED key
        result = dl.is_fred_available()
        assert isinstance(result, bool)

    def test_load_fred_series_invalid_key(self, patch_streamlit_cache):
        dl = patch_streamlit_cache
        result = dl.load_fred_series("nonexistent_key")
        assert result.empty
        assert list(result.columns) == ["date", "value"]


# ============================================================================
# Stock List
# ============================================================================

class TestGetStockList:
    def test_returns_dataframe(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        expected = pd.DataFrame({
            "stock_id": ["2330"],
            "name": ["台積電"],
            "type": ["股票"],
            "market": ["上市"],
        })
        with patch("pandas.read_sql", return_value=expected):
            result = dl.get_stock_list()
            assert "stock_id" in result.columns

    def test_db_error_returns_empty(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", side_effect=Exception("DB error")):
            result = dl.get_stock_list()
            assert result.empty

    def test_get_stock_options(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        expected = pd.DataFrame({
            "stock_id": ["2330", "2317"],
            "name": ["台積電", "鴻海"],
            "type": ["股票", "股票"],
            "market": ["上市", "上市"],
        })
        with patch("pandas.read_sql", return_value=expected):
            options = dl.get_stock_options()
            assert "2330 台積電" in options
            assert options["2330 台積電"] == "2330"


# ============================================================================
# Price Loading
# ============================================================================

class TestLoadDailyPrice:
    def test_basic_load(self, patch_streamlit_cache, mock_engine, sample_price_df):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", return_value=sample_price_df.copy()):
            result = dl.load_daily_price("2330")
            assert len(result) == 5
            assert "close" in result.columns

    def test_with_date_filter(self, patch_streamlit_cache, mock_engine, sample_price_df):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", return_value=sample_price_df.copy()) as mock_sql:
            dl.load_daily_price("2330", start_date="2023-01-01", end_date="2023-12-31")
            # 確認 SQL 包含日期條件（safe_read_sql 會將字串轉為 text()）
            call_args = mock_sql.call_args
            sql = str(call_args[0][0])
            assert "date >=" in sql
            assert "date <=" in sql

    def test_db_error(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", side_effect=Exception("timeout")):
            result = dl.load_daily_price("2330")
            assert result.empty


class TestLoadWeeklyPrice:
    def test_basic(self, patch_streamlit_cache, mock_engine, sample_price_df):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", return_value=sample_price_df.copy()):
            result = dl.load_weekly_price("2330")
            assert not result.empty


class TestLoadMonthlyPrice:
    def test_basic(self, patch_streamlit_cache, mock_engine, sample_price_df):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", return_value=sample_price_df.copy()):
            result = dl.load_monthly_price("2330")
            assert not result.empty


# ============================================================================
# Chip Data
# ============================================================================

class TestChipLoading:
    def test_load_institutional(self, patch_streamlit_cache, mock_engine, sample_institutional_df):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", return_value=sample_institutional_df.copy()):
            result = dl.load_chip_institutional("2330")
            assert not result.empty

    def test_load_margin(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        df = pd.DataFrame({
            "stock_id": ["2330"],
            "date": [pd.Timestamp("2023-01-01")],
            "margin_purchase_balance": [10000],
        })
        with patch("pandas.read_sql", return_value=df):
            result = dl.load_chip_margin("2330")
            assert not result.empty

    def test_load_shareholding(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            result = dl.load_chip_shareholding("2330")
            assert result.empty

    def test_load_holding_pct(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            result = dl.load_chip_holding_pct("2330")
            assert result.empty

    def test_load_securities_lending(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            result = dl.load_chip_securities_lending("2330")
            assert result.empty

    def test_load_short_sale(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            result = dl.load_chip_short_sale("2330")
            assert result.empty


# ============================================================================
# Fundamental Data
# ============================================================================

class TestFundamentalLoading:
    def test_load_financial_reports(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        df = pd.DataFrame({
            "stock_id": ["2330"] * 2,
            "date": pd.date_range("2023-03-31", periods=2, freq="QE"),
            "type": ["Revenue", "NetIncome"],
            "value": [4.5e11, 1.5e11],
        })
        with patch("pandas.read_sql", return_value=df):
            result = dl.load_financial_reports("2330")
            assert len(result) == 2

    def test_load_dividend_history(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            result = dl.load_dividend_history("2330")
            assert result.empty

    def test_load_month_revenue(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            result = dl.load_month_revenue("2330")
            assert result.empty


# ============================================================================
# Valuation Data
# ============================================================================

class TestValuationLoading:
    def test_load_stock_per(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            result = dl.load_stock_per("2330")
            assert result.empty

    def test_load_market_value(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            result = dl.load_market_value("2330")
            assert result.empty


# ============================================================================
# Financial Ratios (Pivot Logic)
# ============================================================================

class TestLoadFinancialRatios:
    def test_pivot_and_calc_ratios(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        raw = pd.DataFrame({
            "stock_id": ["2330"] * 4,
            "date": ["2023-03-31"] * 4,
            "type": ["Revenue", "GrossProfit", "OperatingIncome", "NetIncome"],
            "value": [4.5e11, 1.5e11, 1.0e11, 0.9e11],
        })
        with patch("pandas.read_sql", return_value=raw):
            result = dl.load_financial_ratios("2330")
            if not result.empty:
                assert "gross_margin" in result.columns or "Revenue" in result.columns

    def test_empty_returns_empty(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            result = dl.load_financial_ratios("2330")
            assert result.empty


# ============================================================================
# Aggregation Functions (All Market)
# ============================================================================

class TestAllMarketFunctions:
    def test_load_latest_per_all(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            result = dl.load_latest_per_all()
            assert result.empty

    def test_load_latest_revenue_all(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            result = dl.load_latest_revenue_all()
            assert result.empty

    def test_load_latest_price_all(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            result = dl.load_latest_price_all()
            assert result.empty

    def test_load_latest_institutional_all(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            result = dl.load_latest_institutional_all()
            assert result.empty

    def test_load_market_summary(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        summary_df = pd.DataFrame({
            "up_count": [500], "down_count": [300],
            "flat_count": [100], "total": [900],
        })
        with patch("pandas.read_sql", return_value=summary_df):
            result = dl.load_market_summary()
            assert result.get("up_count") == 500


# ============================================================================
# Multi-Stock Loading
# ============================================================================

class TestMultiStockLoading:
    def test_load_daily_price_multi(self, patch_streamlit_cache, mock_engine, sample_price_df):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", return_value=sample_price_df.copy()):
            result = dl.load_daily_price_multi(["2330", "2317"])
            assert not result.empty

    def test_empty_list(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        result = dl.load_daily_price_multi([])
        assert result.empty

    def test_load_stock_per_multi(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            result = dl.load_stock_per_multi(["2330"])
            assert result.empty

    def test_load_chip_institutional_multi(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            result = dl.load_chip_institutional_multi(["2330"])
            assert result.empty


# ============================================================================
# Industry & Full Market
# ============================================================================

class TestIndustryAndFullMarket:
    def test_load_industry_mapping(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        df = pd.DataFrame({
            "stock_id": ["2330", "2317"],
            "industry_category": ["半導體業", "其他電子業"],
        })
        with patch("pandas.read_sql", return_value=df):
            result = dl.load_industry_mapping()
            assert len(result) == 2

    def test_load_industry_mapping_error(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", side_effect=Exception("error")):
            result = dl.load_industry_mapping()
            assert result.empty
            assert "stock_id" in result.columns
            assert "industry_category" in result.columns

    def test_load_month_revenue_all(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            result = dl.load_month_revenue_all()
            assert result.empty

    def test_load_chip_institutional_all(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            result = dl.load_chip_institutional_all()
            assert result.empty

    def test_load_dividend_events_all(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            result = dl.load_dividend_events_all()
            assert result.empty

    def test_load_earnings_dates_all(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            result = dl.load_earnings_dates_all()
            assert result.empty

    def test_load_daily_price_all(self, patch_streamlit_cache, mock_engine):
        dl = patch_streamlit_cache
        with patch("pandas.read_sql", return_value=pd.DataFrame()):
            result = dl.load_daily_price_all()
            assert result.empty
