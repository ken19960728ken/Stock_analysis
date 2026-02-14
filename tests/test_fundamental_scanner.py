"""
Tests for fundamental_scanner.py
Tests the FundamentalScanner class which fetches financial statements and dividends.
Focus on stock 2330 (TSMC).
"""

import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from scanners.fundamental_scanner import FundamentalScanner, FOCUS_METRICS


class TestFundamentalScannerInitialization:
    """Test FundamentalScanner initialization and configuration"""

    def test_fundamental_scanner_instantiation(
        self, mock_finmind_client, mock_rate_limiter, mock_yfinance
    ):
        """Test that FundamentalScanner can be instantiated with proper attributes"""
        scanner = FundamentalScanner()
        assert scanner.name == "FundamentalScanner"
        assert scanner.resume_table == "financial_reports"
        assert scanner.fm_loader is not None
        assert scanner.limiter is not None
        assert scanner.yahoo_limiter is not None

    def test_fundamental_scanner_inherits_from_base(self):
        """Test that FundamentalScanner inherits from BaseScanner"""
        from core.scanner_base import BaseScanner
        assert issubclass(FundamentalScanner, BaseScanner)

    def test_focus_metrics_defined(self):
        """Test that FOCUS_METRICS is properly configured"""
        assert len(FOCUS_METRICS) > 0
        assert "Revenue" in FOCUS_METRICS
        assert "NetIncome" in FOCUS_METRICS
        assert "TotalAssets" in FOCUS_METRICS
        assert "TotalEquity" in FOCUS_METRICS

    def test_dual_rate_limiters(self, mock_finmind_client, mock_rate_limiter):
        """Test that scanner has separate limiters for FinMind and Yahoo"""
        scanner = FundamentalScanner()
        assert scanner.limiter is not None
        assert scanner.yahoo_limiter is not None
        # Both should be RateLimiter instances
        assert hasattr(scanner.limiter, "wait")
        assert hasattr(scanner.yahoo_limiter, "wait")


class TestFundamentalScannerFetchOne:
    """Test fetch_one method for single stock"""

    def test_fetch_one_with_string_stock_id(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_yfinance,
        mock_db_save,
        sample_stock_id,
        sample_financial_statements_data,
        sample_dividend_history_data,
    ):
        """Test fetch_one with string stock_id"""
        scanner = FundamentalScanner()

        # Mock financial statements
        scanner.fm_loader.taiwan_stock_financial_statement.return_value = (
            sample_financial_statements_data
        )
        scanner.fm_loader.taiwan_stock_balance_sheet.return_value = None

        result = scanner.fetch_one(sample_stock_id)
        assert result is True
        mock_db_save.assert_called()

    def test_fetch_one_with_dict_target(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_yfinance,
        mock_db_save,
        sample_stock_dict,
        sample_financial_statements_data,
    ):
        """Test fetch_one with dict target"""
        scanner = FundamentalScanner()

        scanner.fm_loader.taiwan_stock_financial_statement.return_value = (
            sample_financial_statements_data
        )
        scanner.fm_loader.taiwan_stock_balance_sheet.return_value = None

        result = scanner.fetch_one(sample_stock_dict)
        assert result is True

    def test_fetch_one_financial_statements_and_dividends(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_yfinance,
        mock_db_save,
        sample_stock_id,
        sample_financial_statements_data,
    ):
        """Test fetch_one with both financial statements and dividends"""
        scanner = FundamentalScanner()

        scanner.fm_loader.taiwan_stock_financial_statement.return_value = (
            sample_financial_statements_data
        )
        scanner.fm_loader.taiwan_stock_balance_sheet.return_value = None

        result = scanner.fetch_one(sample_stock_id)
        assert result is True
        # Should call save_to_db at least twice (financial reports + dividends)
        assert mock_db_save.call_count >= 1

    def test_fetch_one_no_data_returns_false(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_yfinance,
        mock_db_save,
        sample_stock_id,
    ):
        """Test fetch_one returns False when no data is fetched"""
        scanner = FundamentalScanner()

        scanner.fm_loader.taiwan_stock_financial_statement.return_value = None
        scanner.fm_loader.taiwan_stock_balance_sheet.return_value = None

        # Mock Ticker to return empty dividends
        with patch("scanners.fundamental_scanner.yf.Ticker") as mock_ticker:
            ticker_obj = MagicMock()
            ticker_obj.dividends = pd.Series(dtype=float)
            mock_ticker.return_value = ticker_obj

            result = scanner.fetch_one(sample_stock_id)
            assert result is False


class TestFundamentalScannerFinancialStatements:
    """Test _fetch_financial_statements method"""

    def test_fetch_financial_statements_income_sheet(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        sample_stock_id,
        sample_financial_statements_data,
    ):
        """Test fetching income statement data"""
        scanner = FundamentalScanner()

        scanner.fm_loader.taiwan_stock_financial_statement.return_value = (
            sample_financial_statements_data
        )
        scanner.fm_loader.taiwan_stock_balance_sheet.return_value = None

        result = scanner._fetch_financial_statements(sample_stock_id)
        assert result is not None
        assert isinstance(result, pd.DataFrame)

    def test_fetch_financial_statements_balance_sheet(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        sample_stock_id,
        sample_financial_statements_data,
    ):
        """Test fetching balance sheet data"""
        scanner = FundamentalScanner()

        scanner.fm_loader.taiwan_stock_financial_statement.return_value = None
        scanner.fm_loader.taiwan_stock_balance_sheet.return_value = (
            sample_financial_statements_data
        )

        result = scanner._fetch_financial_statements(sample_stock_id)
        assert result is not None

    def test_fetch_financial_statements_filters_focus_metrics(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        sample_stock_id,
    ):
        """Test that financial statements are filtered to FOCUS_METRICS"""
        scanner = FundamentalScanner()

        # Create data with mixed metrics (some in FOCUS_METRICS, some not)
        df_income = pd.DataFrame({
            "date": [datetime.date(2023, 3, 31)] * 4,
            "stock_id": sample_stock_id,
            "type": ["Revenue", "NetIncome", "UnknownMetric", "AnotherUnknown"],
            "value": [450000000000, 150000000000, 100000, 50000],
        })

        scanner.fm_loader.taiwan_stock_financial_statement.return_value = df_income
        scanner.fm_loader.taiwan_stock_balance_sheet.return_value = None

        result = scanner._fetch_financial_statements(sample_stock_id)

        # Should only contain metrics in FOCUS_METRICS
        if result is not None:
            assert all(metric in FOCUS_METRICS for metric in result["type"].unique())

    def test_fetch_financial_statements_date_conversion(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        sample_stock_id,
    ):
        """Test that dates are converted to date objects"""
        scanner = FundamentalScanner()

        df_income = pd.DataFrame({
            "date": ["2023-03-31", "2023-06-30"],
            "stock_id": sample_stock_id,
            "type": ["Revenue", "Revenue"],
            "value": [450000000000, 460000000000],
        })

        scanner.fm_loader.taiwan_stock_financial_statement.return_value = df_income
        scanner.fm_loader.taiwan_stock_balance_sheet.return_value = None

        result = scanner._fetch_financial_statements(sample_stock_id)
        assert result is not None
        # Dates should be converted to date objects
        assert result["date"].dtype == object or result["date"].dtype == "datetime64[ns]"

    def test_fetch_financial_statements_combines_income_and_balance(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        sample_stock_id,
    ):
        """Test that income and balance sheet data are combined"""
        scanner = FundamentalScanner()

        df_income = pd.DataFrame({
            "date": [datetime.date(2023, 3, 31)] * 2,
            "stock_id": sample_stock_id,
            "type": ["Revenue", "NetIncome"],
            "value": [450000000000, 150000000000],
        })

        df_balance = pd.DataFrame({
            "date": [datetime.date(2023, 3, 31)] * 2,
            "stock_id": sample_stock_id,
            "type": ["TotalAssets", "TotalEquity"],
            "value": [2000000000000, 1200000000000],
        })

        scanner.fm_loader.taiwan_stock_financial_statement.return_value = df_income
        scanner.fm_loader.taiwan_stock_balance_sheet.return_value = df_balance

        result = scanner._fetch_financial_statements(sample_stock_id)
        assert result is not None
        assert len(result) >= 2

    def test_fetch_financial_statements_returns_none_on_empty(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        sample_stock_id,
    ):
        """Test that None is returned when no data after filtering"""
        scanner = FundamentalScanner()

        df_empty = pd.DataFrame({
            "date": [],
            "stock_id": [],
            "type": [],
            "value": [],
        })

        scanner.fm_loader.taiwan_stock_financial_statement.return_value = df_empty
        scanner.fm_loader.taiwan_stock_balance_sheet.return_value = None

        result = scanner._fetch_financial_statements(sample_stock_id)
        assert result is None


class TestFundamentalScannerDividends:
    """Test _fetch_dividends method"""

    def test_fetch_dividends_success(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_yfinance,
        mock_db_save,
        sample_stock_id,
        sample_dividend_history_data,
    ):
        """Test successful dividend fetching"""
        scanner = FundamentalScanner()

        with patch("scanners.fundamental_scanner.yf.Ticker") as mock_ticker:
            ticker_obj = MagicMock()
            dates = pd.DatetimeIndex(
                ["2023-01-15", "2023-07-15", "2024-01-15"],
                dtype="datetime64[ns]",
            )
            ticker_obj.dividends = pd.Series([10.0, 6.0, 11.0], index=dates)
            mock_ticker.return_value = ticker_obj

            result = scanner._fetch_dividends(sample_stock_id)
            assert result is not None
            assert isinstance(result, pd.DataFrame)
            assert "dividend" in result.columns

    def test_fetch_dividends_empty_returns_none(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        sample_stock_id,
    ):
        """Test that None is returned for stocks with no dividends"""
        scanner = FundamentalScanner()

        with patch("scanners.fundamental_scanner.yf.Ticker") as mock_ticker:
            ticker_obj = MagicMock()
            ticker_obj.dividends = pd.Series(dtype=float)
            mock_ticker.return_value = ticker_obj

            result = scanner._fetch_dividends(sample_stock_id)
            assert result is None

    def test_fetch_dividends_correct_columns(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        sample_stock_id,
    ):
        """Test that dividend DataFrame has correct columns"""
        scanner = FundamentalScanner()

        with patch("scanners.fundamental_scanner.yf.Ticker") as mock_ticker:
            ticker_obj = MagicMock()
            dates = pd.DatetimeIndex([datetime.datetime(2023, 1, 15)])
            ticker_obj.dividends = pd.Series([10.0], index=dates)
            mock_ticker.return_value = ticker_obj

            result = scanner._fetch_dividends(sample_stock_id)
            assert result is not None
            assert "date" in result.columns
            assert "stock_id" in result.columns
            assert "dividend" in result.columns

    def test_fetch_dividends_stock_id_in_result(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        sample_stock_id,
    ):
        """Test that stock_id is included in dividend DataFrame"""
        scanner = FundamentalScanner()

        with patch("scanners.fundamental_scanner.yf.Ticker") as mock_ticker:
            ticker_obj = MagicMock()
            dates = pd.DatetimeIndex([datetime.datetime(2023, 1, 15)])
            ticker_obj.dividends = pd.Series([10.0], index=dates)
            mock_ticker.return_value = ticker_obj

            result = scanner._fetch_dividends(sample_stock_id)
            assert result["stock_id"].iloc[0] == sample_stock_id

    def test_fetch_dividends_yahoo_symbol_format(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        sample_stock_id,
    ):
        """Test that Yahoo symbol format is correct (stock_id.TW)"""
        scanner = FundamentalScanner()

        with patch("scanners.fundamental_scanner.yf.Ticker") as mock_ticker:
            ticker_obj = MagicMock()
            ticker_obj.dividends = pd.Series(dtype=float)
            mock_ticker.return_value = ticker_obj

            scanner._fetch_dividends(sample_stock_id)

            # Verify correct ticker symbol was used
            expected_symbol = f"{sample_stock_id}.TW"
            mock_ticker.assert_called_once_with(expected_symbol)


class TestFundamentalScannerRateLimiting:
    """Test rate limiting behavior"""

    def test_rate_limiter_wait_after_financial_statements(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_yfinance,
        mock_db_save,
        sample_stock_id,
        sample_financial_statements_data,
    ):
        """Test that FinMind rate limiter wait is called"""
        scanner = FundamentalScanner()

        scanner.fm_loader.taiwan_stock_financial_statement.return_value = (
            sample_financial_statements_data
        )
        scanner.fm_loader.taiwan_stock_balance_sheet.return_value = None

        with patch("scanners.fundamental_scanner.yf.Ticker") as mock_ticker:
            ticker_obj = MagicMock()
            ticker_obj.dividends = pd.Series(dtype=float)
            mock_ticker.return_value = ticker_obj

            scanner.fetch_one(sample_stock_id)

            # Verify wait was called
            assert scanner.limiter.wait.called

    def test_yahoo_rate_limiter_wait_after_dividends(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        sample_stock_id,
    ):
        """Test that Yahoo rate limiter wait is called"""
        scanner = FundamentalScanner()

        scanner.fm_loader.taiwan_stock_financial_statement.return_value = None
        scanner.fm_loader.taiwan_stock_balance_sheet.return_value = None

        with patch("scanners.fundamental_scanner.yf.Ticker") as mock_ticker:
            ticker_obj = MagicMock()
            ticker_obj.dividends = pd.Series(dtype=float)
            mock_ticker.return_value = ticker_obj

            scanner.fetch_one(sample_stock_id)

            # Verify yahoo_limiter.wait was called
            assert scanner.yahoo_limiter.wait.called


class TestFundamentalScannerIntegration:
    """Integration tests for FundamentalScanner"""

    def test_scanner_name_attribute(self):
        """Test that scanner has correct name"""
        scanner = FundamentalScanner()
        assert scanner.name == "FundamentalScanner"

    def test_resume_table_attribute(self):
        """Test that resume_table is set to financial_reports"""
        scanner = FundamentalScanner()
        assert scanner.resume_table == "financial_reports"

    def test_fetch_one_returns_true_on_any_success(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_yfinance,
        mock_db_save,
        sample_stock_id,
        sample_financial_statements_data,
    ):
        """Test that fetch_one returns True if any data source succeeds"""
        scanner = FundamentalScanner()

        # Only financial statements succeed
        scanner.fm_loader.taiwan_stock_financial_statement.return_value = (
            sample_financial_statements_data
        )
        scanner.fm_loader.taiwan_stock_balance_sheet.return_value = None

        # Mock dividend fetching to return None
        with patch("scanners.fundamental_scanner.yf.Ticker") as mock_ticker:
            ticker_obj = MagicMock()
            ticker_obj.dividends = pd.Series(dtype=float)
            mock_ticker.return_value = ticker_obj

            result = scanner.fetch_one(sample_stock_id)
            assert result is True

    def test_focus_metrics_include_key_indicators(self):
        """Test that FOCUS_METRICS includes essential financial indicators"""
        essential_metrics = [
            "Revenue",
            "NetIncome",
            "TotalAssets",
            "TotalEquity",
            "TotalLiabilities",
        ]
        for metric in essential_metrics:
            assert metric in FOCUS_METRICS
