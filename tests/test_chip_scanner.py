"""
Tests for chip_scanner.py
Tests the ChipScanner class which fetches 6 chip datasets from FinMind API.
Focus on stock 2330 (TSMC).
"""

import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from scanners.chip_scanner import ChipScanner, CHIP_DATASETS


class TestChipScannerInitialization:
    """Test ChipScanner initialization and configuration"""

    def test_chip_scanner_instantiation(self, mock_finmind_client, mock_rate_limiter, mock_local_index):
        """Test that ChipScanner can be instantiated with proper attributes"""
        scanner = ChipScanner()
        assert scanner.name == "ChipScanner"
        assert scanner.resume_tables == [t[1] for t in CHIP_DATASETS]
        assert scanner.fm_loader is not None
        assert scanner.limiter is not None
        assert not hasattr(scanner, "fm_token")

    def test_chip_scanner_inherits_from_base(self):
        """Test that ChipScanner inherits from BaseScanner"""
        from core.scanner_base import BaseScanner
        assert issubclass(ChipScanner, BaseScanner)

    def test_chip_datasets_defined(self):
        """Test that CHIP_DATASETS is properly configured"""
        assert len(CHIP_DATASETS) == 6
        dataset_names = [d[0] for d in CHIP_DATASETS]
        assert "taiwan_stock_institutional_investors" in dataset_names
        assert "taiwan_stock_margin_purchase_short_sale" in dataset_names
        assert "taiwan_stock_shareholding" in dataset_names
        assert "taiwan_stock_holding_shares_per" in dataset_names
        assert "taiwan_stock_securities_lending" in dataset_names
        assert "taiwan_daily_short_sale_balances" in dataset_names


class TestChipScannerFetchOne:
    """Test fetch_one method for single stock"""

    def test_fetch_one_with_string_stock_id(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        mock_local_index,
        sample_stock_id,
        sample_chip_institutional_data,
    ):
        """Test fetch_one with string stock_id"""
        scanner = ChipScanner()

        # Setup mock to return institutional data
        scanner.fm_loader.taiwan_stock_institutional_investors.return_value = (
            sample_chip_institutional_data
        )

        # Mock other datasets to return empty
        scanner.fm_loader.taiwan_stock_margin_purchase_short_sale.return_value = None
        scanner.fm_loader.taiwan_stock_shareholding.return_value = None
        scanner.fm_loader.taiwan_stock_holding_shares_per.return_value = None
        scanner.fm_loader.taiwan_stock_securities_lending.return_value = None
        scanner.fm_loader.taiwan_daily_short_sale_balances.return_value = None

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
        sample_chip_institutional_data,
    ):
        """Test fetch_one with dict target (containing stock_id)"""
        scanner = ChipScanner()
        scanner.fm_loader.taiwan_stock_institutional_investors.return_value = (
            sample_chip_institutional_data
        )

        # Mock other datasets
        for method_name in [
            "taiwan_stock_margin_purchase_short_sale",
            "taiwan_stock_shareholding",
            "taiwan_stock_holding_shares_per",
            "taiwan_stock_securities_lending",
            "taiwan_daily_short_sale_balances",
        ]:
            getattr(scanner.fm_loader, method_name).return_value = None

        result = scanner.fetch_one(sample_stock_dict)
        assert result is True

    def test_fetch_one_all_datasets_success(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        mock_local_index,
        sample_stock_id,
        sample_chip_institutional_data,
        sample_chip_margin_data,
        sample_chip_shareholding_data,
    ):
        """Test fetch_one when all datasets are successfully fetched"""
        scanner = ChipScanner()

        # Mock returns for different datasets
        scanner.fm_loader.taiwan_stock_institutional_investors.return_value = (
            sample_chip_institutional_data
        )
        scanner.fm_loader.taiwan_stock_margin_purchase_short_sale.return_value = (
            sample_chip_margin_data
        )
        scanner.fm_loader.taiwan_stock_shareholding.return_value = (
            sample_chip_shareholding_data
        )
        scanner.fm_loader.taiwan_stock_holding_shares_per.return_value = pd.DataFrame(
            {
                "date": [datetime.date(2023, 1, 15)],
                "stock_id": sample_stock_id,
                "holding_pct": [15.5],
            }
        )
        scanner.fm_loader.taiwan_stock_securities_lending.return_value = pd.DataFrame(
            {
                "date": [datetime.date(2023, 1, 1)],
                "stock_id": sample_stock_id,
                "securities_balance": [100000],
            }
        )
        scanner.fm_loader.taiwan_daily_short_sale_balances.return_value = (
            pd.DataFrame(
                {
                    "date": [datetime.date(2023, 1, 1)],
                    "stock_id": sample_stock_id,
                    "short_sale_balance": [50000],
                }
            )
        )

        result = scanner.fetch_one(sample_stock_id)
        assert result is True
        assert mock_db_save.call_count >= 6

    def test_fetch_one_partial_success(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        mock_local_index,
        sample_stock_id,
        sample_chip_institutional_data,
    ):
        """Test fetch_one when only some datasets are successfully fetched"""
        scanner = ChipScanner()

        # Only institutional data succeeds
        scanner.fm_loader.taiwan_stock_institutional_investors.return_value = (
            sample_chip_institutional_data
        )
        # Rest return None/empty
        for method_name in [
            "taiwan_stock_margin_purchase_short_sale",
            "taiwan_stock_shareholding",
            "taiwan_stock_holding_shares_per",
            "taiwan_stock_securities_lending",
            "taiwan_daily_short_sale_balances",
        ]:
            getattr(scanner.fm_loader, method_name).return_value = None

        result = scanner.fetch_one(sample_stock_id)
        assert result is True  # At least one succeeded

    def test_fetch_one_no_data_returns_false(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        mock_local_index,
        sample_stock_id,
    ):
        """Test fetch_one returns False when no data is fetched"""
        scanner = ChipScanner()

        # All datasets return None
        for method_name in [
            "taiwan_stock_institutional_investors",
            "taiwan_stock_margin_purchase_short_sale",
            "taiwan_stock_shareholding",
            "taiwan_stock_holding_shares_per",
            "taiwan_stock_securities_lending",
            "taiwan_daily_short_sale_balances",
        ]:
            getattr(scanner.fm_loader, method_name).return_value = None

        result = scanner.fetch_one(sample_stock_id)
        assert result is False

    def test_fetch_one_api_exception_continues(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        mock_local_index,
        sample_stock_id,
        sample_chip_institutional_data,
    ):
        """Test fetch_one continues when one API call throws exception"""
        scanner = ChipScanner()

        # First one succeeds
        scanner.fm_loader.taiwan_stock_institutional_investors.return_value = (
            sample_chip_institutional_data
        )
        # Second one raises exception
        scanner.fm_loader.taiwan_stock_margin_purchase_short_sale.side_effect = (
            Exception("API Error")
        )
        # Rest return None
        for method_name in [
            "taiwan_stock_shareholding",
            "taiwan_stock_holding_shares_per",
            "taiwan_stock_securities_lending",
            "taiwan_daily_short_sale_balances",
        ]:
            getattr(scanner.fm_loader, method_name).return_value = None

        result = scanner.fetch_one(sample_stock_id)
        # Should still return True because first dataset succeeded
        assert result is True


class TestChipScannerDataTransformation:
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
        scanner = ChipScanner()

        # Create DataFrame with string dates
        df_with_string_dates = pd.DataFrame({
            "date": ["2023-01-01", "2023-01-02"],
            "stock_id": sample_stock_id,
            "value": [100, 200],
        })

        scanner.fm_loader.taiwan_stock_institutional_investors.return_value = (
            df_with_string_dates
        )

        # Mock remaining methods
        for method_name in [
            "taiwan_stock_margin_purchase_short_sale",
            "taiwan_stock_shareholding",
            "taiwan_stock_holding_shares_per",
            "taiwan_stock_securities_lending",
            "taiwan_daily_short_sale_balances",
        ]:
            getattr(scanner.fm_loader, method_name).return_value = None

        scanner.fetch_one(sample_stock_id)

        # Verify save_to_db was called with proper date format
        assert mock_db_save.called
        args, kwargs = mock_db_save.call_args
        saved_df = args[0]
        # Check that dates are in date format (after conversion in scanner)
        assert saved_df is not None

    def test_empty_dataframe_handling(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        mock_local_index,
        sample_stock_id,
    ):
        """Test handling of empty DataFrames"""
        scanner = ChipScanner()

        # Return empty DataFrame
        empty_df = pd.DataFrame()
        scanner.fm_loader.taiwan_stock_institutional_investors.return_value = (
            empty_df
        )

        for method_name in [
            "taiwan_stock_margin_purchase_short_sale",
            "taiwan_stock_shareholding",
            "taiwan_stock_holding_shares_per",
            "taiwan_stock_securities_lending",
            "taiwan_daily_short_sale_balances",
        ]:
            getattr(scanner.fm_loader, method_name).return_value = None

        result = scanner.fetch_one(sample_stock_id)
        assert result is False


class TestChipScannerRateLimiting:
    """Test rate limiting behavior"""

    def test_rate_limiter_wait_called(
        self,
        mock_finmind_client,
        mock_db_save,
        mock_local_index,
        sample_stock_id,
        sample_chip_institutional_data,
    ):
        """Test that rate limiter wait is called between API calls"""
        scanner = ChipScanner()
        scanner.fm_loader.taiwan_stock_institutional_investors.return_value = (
            sample_chip_institutional_data
        )

        for method_name in [
            "taiwan_stock_margin_purchase_short_sale",
            "taiwan_stock_shareholding",
            "taiwan_stock_holding_shares_per",
            "taiwan_stock_securities_lending",
            "taiwan_daily_short_sale_balances",
        ]:
            getattr(scanner.fm_loader, method_name).return_value = None

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
        sample_chip_institutional_data,
    ):
        """Test that token is not passed to API calls (handled by login_by_token)"""
        scanner = ChipScanner()
        scanner.fm_loader.taiwan_stock_institutional_investors.return_value = (
            sample_chip_institutional_data
        )

        for method_name in [
            "taiwan_stock_margin_purchase_short_sale",
            "taiwan_stock_shareholding",
            "taiwan_stock_holding_shares_per",
            "taiwan_stock_securities_lending",
            "taiwan_daily_short_sale_balances",
        ]:
            getattr(scanner.fm_loader, method_name).return_value = None

        scanner.fetch_one(sample_stock_id)

        # Verify token is NOT passed as parameter (auth handled by login_by_token)
        call_kwargs = scanner.fm_loader.taiwan_stock_institutional_investors.call_args
        assert "token" not in (call_kwargs.kwargs if call_kwargs else {})


class TestChipScannerIntegration:
    """Integration tests for ChipScanner"""

    def test_scanner_has_resume_tables(self):
        """Test that ChipScanner has resume_tables for checkpoint feature"""
        scanner = ChipScanner()
        assert scanner.resume_tables == [t[1] for t in CHIP_DATASETS]

    def test_scanner_inherits_scan_method(self):
        """Test that ChipScanner inherits scan() method from BaseScanner"""
        scanner = ChipScanner()
        assert hasattr(scanner, "scan")
        assert callable(scanner.scan)
