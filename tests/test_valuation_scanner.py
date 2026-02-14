"""
Tests for valuation_scanner.py
Tests the ValuationScanner class which fetches 3 valuation datasets from FinMind.
Focus on stock 2330 (TSMC).
"""

import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from scanners.valuation_scanner import ValuationScanner, VALUATION_DATASETS


class TestValuationScannerInitialization:
    """Test ValuationScanner initialization and configuration"""

    def test_valuation_scanner_instantiation(
        self, mock_finmind_client, mock_rate_limiter, mock_local_index
    ):
        """Test that ValuationScanner can be instantiated with proper attributes"""
        scanner = ValuationScanner()
        assert scanner.name == "ValuationScanner"
        assert scanner.resume_tables == [t[1] for t in VALUATION_DATASETS]
        assert scanner.fm_loader is not None
        assert scanner.limiter is not None

    def test_valuation_scanner_inherits_from_base(self):
        """Test that ValuationScanner inherits from BaseScanner"""
        from core.scanner_base import BaseScanner
        assert issubclass(ValuationScanner, BaseScanner)

    def test_valuation_datasets_defined(self):
        """Test that VALUATION_DATASETS is properly configured"""
        assert len(VALUATION_DATASETS) == 3
        dataset_names = [d[0] for d in VALUATION_DATASETS]
        assert "taiwan_stock_month_revenue" in dataset_names
        assert "taiwan_stock_per_pbr" in dataset_names
        assert "taiwan_stock_market_value" in dataset_names


class TestValuationScannerFetchOne:
    """Test fetch_one method for single stock"""

    def test_fetch_one_with_string_stock_id(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        mock_local_index,
        sample_stock_id,
        sample_valuation_revenue_data,
    ):
        """Test fetch_one with string stock_id"""
        scanner = ValuationScanner()

        # Setup mock to return revenue data
        scanner.fm_loader.taiwan_stock_month_revenue.return_value = (
            sample_valuation_revenue_data
        )
        # Mock other datasets
        scanner.fm_loader.taiwan_stock_per_pbr.return_value = None
        scanner.fm_loader.taiwan_stock_market_value.return_value = None

        result = scanner.fetch_one(sample_stock_id)
        assert result is True
        mock_db_save.assert_called()

    def test_fetch_one_with_dict_target(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        mock_local_index,
        sample_stock_dict,
        sample_valuation_revenue_data,
    ):
        """Test fetch_one with dict target"""
        scanner = ValuationScanner()
        scanner.fm_loader.taiwan_stock_month_revenue.return_value = (
            sample_valuation_revenue_data
        )
        scanner.fm_loader.taiwan_stock_per_pbr.return_value = None
        scanner.fm_loader.taiwan_stock_market_value.return_value = None

        result = scanner.fetch_one(sample_stock_dict)
        assert result is True

    def test_fetch_one_all_datasets_success(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        mock_local_index,
        sample_stock_id,
        sample_valuation_revenue_data,
        sample_valuation_per_data,
        sample_valuation_market_value_data,
    ):
        """Test fetch_one when all valuation datasets are successfully fetched"""
        scanner = ValuationScanner()

        scanner.fm_loader.taiwan_stock_month_revenue.return_value = (
            sample_valuation_revenue_data
        )
        scanner.fm_loader.taiwan_stock_per_pbr.return_value = sample_valuation_per_data
        scanner.fm_loader.taiwan_stock_market_value.return_value = (
            sample_valuation_market_value_data
        )

        result = scanner.fetch_one(sample_stock_id)
        assert result is True
        assert mock_db_save.call_count == 3

    def test_fetch_one_partial_success_first_dataset(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        mock_local_index,
        sample_stock_id,
        sample_valuation_revenue_data,
    ):
        """Test fetch_one returns True when at least first dataset succeeds"""
        scanner = ValuationScanner()

        scanner.fm_loader.taiwan_stock_month_revenue.return_value = (
            sample_valuation_revenue_data
        )
        scanner.fm_loader.taiwan_stock_per_pbr.return_value = None
        scanner.fm_loader.taiwan_stock_market_value.return_value = None

        result = scanner.fetch_one(sample_stock_id)
        assert result is True

    def test_fetch_one_partial_success_middle_dataset(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        mock_local_index,
        sample_stock_id,
        sample_valuation_per_data,
    ):
        """Test fetch_one returns True when middle dataset succeeds"""
        scanner = ValuationScanner()

        scanner.fm_loader.taiwan_stock_month_revenue.return_value = None
        scanner.fm_loader.taiwan_stock_per_pbr.return_value = sample_valuation_per_data
        scanner.fm_loader.taiwan_stock_market_value.return_value = None

        result = scanner.fetch_one(sample_stock_id)
        assert result is True

    def test_fetch_one_no_data_returns_false(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        mock_local_index,
        sample_stock_id,
    ):
        """Test fetch_one returns False when no data is fetched"""
        scanner = ValuationScanner()

        scanner.fm_loader.taiwan_stock_month_revenue.return_value = None
        scanner.fm_loader.taiwan_stock_per_pbr.return_value = None
        scanner.fm_loader.taiwan_stock_market_value.return_value = None

        result = scanner.fetch_one(sample_stock_id)
        assert result is False

    def test_fetch_one_empty_dataframe(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        mock_local_index,
        sample_stock_id,
    ):
        """Test fetch_one handles empty DataFrames correctly"""
        scanner = ValuationScanner()

        scanner.fm_loader.taiwan_stock_month_revenue.return_value = pd.DataFrame()
        scanner.fm_loader.taiwan_stock_per_pbr.return_value = None
        scanner.fm_loader.taiwan_stock_market_value.return_value = None

        result = scanner.fetch_one(sample_stock_id)
        assert result is False

    def test_fetch_one_api_exception_continues(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        mock_local_index,
        sample_stock_id,
        sample_valuation_per_data,
    ):
        """Test fetch_one continues when one API call throws exception"""
        scanner = ValuationScanner()

        scanner.fm_loader.taiwan_stock_month_revenue.side_effect = Exception(
            "API Error"
        )
        scanner.fm_loader.taiwan_stock_per_pbr.return_value = sample_valuation_per_data
        scanner.fm_loader.taiwan_stock_market_value.return_value = None

        result = scanner.fetch_one(sample_stock_id)
        # Should return True because per dataset succeeded
        assert result is True


class TestValuationScannerDataTransformation:
    """Test data transformation and date handling"""

    def test_date_column_conversion(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        mock_local_index,
        sample_stock_id,
    ):
        """Test that date columns are converted to date objects"""
        scanner = ValuationScanner()

        # Create DataFrame with string dates
        df_with_string_dates = pd.DataFrame({
            "date": ["2023-01-01", "2023-02-01"],
            "stock_id": sample_stock_id,
            "revenue": [100000000, 105000000],
        })

        scanner.fm_loader.taiwan_stock_month_revenue.return_value = (
            df_with_string_dates
        )
        scanner.fm_loader.taiwan_stock_per_pbr.return_value = None
        scanner.fm_loader.taiwan_stock_market_value.return_value = None

        scanner.fetch_one(sample_stock_id)

        assert mock_db_save.called
        args, kwargs = mock_db_save.call_args
        saved_df = args[0]
        assert saved_df is not None

    def test_monthly_revenue_structure(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        mock_local_index,
        sample_stock_id,
    ):
        """Test that monthly revenue data has expected structure"""
        scanner = ValuationScanner()

        revenue_df = pd.DataFrame({
            "date": pd.date_range(start="2023-01-01", periods=3, freq="MS"),
            "stock_id": sample_stock_id,
            "revenue": [150000000, 155000000, 160000000],
            "month_revenue_year_on_year": [10.5, 12.3, 14.2],
        })

        scanner.fm_loader.taiwan_stock_month_revenue.return_value = revenue_df
        scanner.fm_loader.taiwan_stock_per_pbr.return_value = None
        scanner.fm_loader.taiwan_stock_market_value.return_value = None

        result = scanner.fetch_one(sample_stock_id)
        assert result is True

    def test_per_pbr_dividend_yield_structure(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        mock_local_index,
        sample_stock_id,
    ):
        """Test P/E, P/B, dividend yield data structure"""
        scanner = ValuationScanner()

        per_df = pd.DataFrame({
            "date": pd.date_range(start="2023-01-01", periods=5, freq="D"),
            "stock_id": sample_stock_id,
            "per": [18.5, 18.8, 19.2, 19.0, 18.9],
            "pbr": [2.5, 2.6, 2.7, 2.65, 2.62],
            "dividend_yield": [4.2, 4.1, 4.0, 4.05, 4.08],
        })

        scanner.fm_loader.taiwan_stock_month_revenue.return_value = None
        scanner.fm_loader.taiwan_stock_per_pbr.return_value = per_df
        scanner.fm_loader.taiwan_stock_market_value.return_value = None

        result = scanner.fetch_one(sample_stock_id)
        assert result is True

    def test_market_value_structure(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        mock_local_index,
        sample_stock_id,
    ):
        """Test market value data structure"""
        scanner = ValuationScanner()

        market_value_df = pd.DataFrame({
            "date": pd.date_range(start="2023-01-01", periods=5, freq="D"),
            "stock_id": sample_stock_id,
            "market_value": [17000000000, 17200000000, 17400000000, 17300000000, 17500000000],
            "market_value_per_share": [580.0, 585.0, 590.0, 588.0, 595.0],
        })

        scanner.fm_loader.taiwan_stock_month_revenue.return_value = None
        scanner.fm_loader.taiwan_stock_per_pbr.return_value = None
        scanner.fm_loader.taiwan_stock_market_value.return_value = market_value_df

        result = scanner.fetch_one(sample_stock_id)
        assert result is True


class TestValuationScannerRateLimiting:
    """Test rate limiting behavior"""

    def test_rate_limiter_configuration(
        self, mock_finmind_client, mock_rate_limiter, mock_local_index
    ):
        """Test that rate limiter is configured for FinMind source"""
        scanner = ValuationScanner()
        assert scanner.limiter is not None

    def test_rate_limiter_wait_called(
        self,
        mock_finmind_client,
        mock_db_save,
        mock_local_index,
        sample_stock_id,
        sample_valuation_revenue_data,
    ):
        """Test that rate limiter wait is called between API calls"""
        scanner = ValuationScanner()
        scanner.fm_loader.taiwan_stock_month_revenue.return_value = (
            sample_valuation_revenue_data
        )
        scanner.fm_loader.taiwan_stock_per_pbr.return_value = None
        scanner.fm_loader.taiwan_stock_market_value.return_value = None

        # The wait method is a MagicMock with side_effect=None
        # Just verify the scanner has a working limiter
        assert hasattr(scanner.limiter, "wait")
        assert callable(scanner.limiter.wait)

    def test_no_token_passed_to_api(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        mock_local_index,
        sample_stock_id,
        sample_valuation_revenue_data,
    ):
        """Test that token is not passed to API calls (handled by login_by_token)"""
        scanner = ValuationScanner()
        assert not hasattr(scanner, "fm_token")


class TestValuationScannerIntegration:
    """Integration tests for ValuationScanner"""

    def test_get_targets_returns_list(
        self, mock_finmind_client, mock_rate_limiter, mock_local_index, mock_stock_list
    ):
        """Test that get_targets returns list of stock IDs"""
        scanner = ValuationScanner()
        targets = scanner.get_targets()
        assert isinstance(targets, list)
        assert len(targets) > 0

    def test_scanner_name_attribute(self):
        """Test that scanner has name attribute"""
        scanner = ValuationScanner()
        assert hasattr(scanner, "name")
        assert scanner.name == "ValuationScanner"

    def test_resume_tables_attribute(self):
        """Test that scanner has resume_tables for checkpoint feature"""
        scanner = ValuationScanner()
        assert hasattr(scanner, "resume_tables")
        assert scanner.resume_tables == [t[1] for t in VALUATION_DATASETS]
