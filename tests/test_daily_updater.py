"""
Tests for daily_updater.py
Tests the DailyUpdater class which batch-fetches daily price + 6 chip datasets
+ valuation data from FinMind API for the entire market.
"""

import datetime
from unittest.mock import MagicMock, call, patch

import pandas as pd
import pytest

from scanners.chip_scanner import CHIP_DATASETS
from scanners.daily_updater import DailyUpdater


@pytest.fixture(autouse=True)
def mock_twse_holidays():
    """Mock TWSE 行事曆 API，避免測試發出真實 HTTP 請求。
    回傳 2023-01-01 為休市日，其餘日期視為交易日。"""
    with patch(
        "scanners.daily_updater._fetch_twse_holidays",
        return_value={"2023-01-01"},
    ):
        yield


# ============================================================================
# TestDailyUpdaterInitialization
# ============================================================================


class TestDailyUpdaterInitialization:
    """Test DailyUpdater initialization and configuration"""

    def test_instantiation(self, mock_finmind_client, mock_rate_limiter):
        """DailyUpdater can be created with fm_loader and limiter attributes"""
        updater = DailyUpdater()
        assert hasattr(updater, "fm_loader")
        assert hasattr(updater, "limiter")
        assert updater.fm_loader is not None
        assert updater.limiter is not None

    def test_uses_finmind_rate_limiter(self, mock_finmind_client, mock_rate_limiter):
        """RateLimiter is created with source='finmind'"""
        updater = DailyUpdater()
        assert updater.limiter.source == "finmind"


# ============================================================================
# TestDailyUpdaterRun
# ============================================================================


class TestDailyUpdaterRun:
    """Test DailyUpdater.run() orchestration"""

    def test_run_default_date_is_today(
        self, mock_finmind_client, mock_rate_limiter, mock_db_save
    ):
        """run() without args uses date.today()"""
        # 固定為週三，確保 is_trading_day 判定為交易日
        fake_today = datetime.date(2023, 1, 4)  # 2023-01-04 是週三
        with patch("scanners.daily_updater.date") as mock_date:
            mock_date.today.return_value = fake_today
            mock_date.side_effect = lambda *a, **kw: datetime.date(*a, **kw)

            updater = DailyUpdater()
            updater.fm_loader.taiwan_stock_daily.return_value = pd.DataFrame()
            updater.run()

        call_kwargs = updater.fm_loader.taiwan_stock_daily.call_args
        assert call_kwargs.kwargs.get("start_date") == "2023-01-04"

    def test_run_with_string_date(
        self, mock_finmind_client, mock_rate_limiter, mock_db_save
    ):
        """run('2023-01-03') parses the string correctly"""
        updater = DailyUpdater()
        updater.fm_loader.taiwan_stock_daily.return_value = pd.DataFrame()
        updater.run("2023-01-03")
        call_kwargs = updater.fm_loader.taiwan_stock_daily.call_args
        assert call_kwargs.kwargs.get("start_date") == "2023-01-03"
        assert call_kwargs.kwargs.get("end_date") == "2023-01-03"

    def test_run_with_date_object(
        self, mock_finmind_client, mock_rate_limiter, mock_db_save
    ):
        """run(date(2023, 1, 3)) accepts date objects"""
        updater = DailyUpdater()
        updater.fm_loader.taiwan_stock_daily.return_value = pd.DataFrame()
        updater.run(datetime.date(2023, 1, 3))
        call_kwargs = updater.fm_loader.taiwan_stock_daily.call_args
        assert call_kwargs.kwargs.get("start_date") == "2023-01-03"

    def test_run_non_trading_day_skips_chip(
        self, mock_finmind_client, mock_rate_limiter, mock_db_save
    ):
        """When price returns empty (non-trading day), chip APIs are NOT called"""
        updater = DailyUpdater()
        updater.fm_loader.taiwan_stock_daily.return_value = pd.DataFrame()
        updater.run("2023-01-01")

        # None of the chip methods should have been called
        for method_name, _, _ in CHIP_DATASETS:
            assert getattr(updater.fm_loader, method_name).call_count == 0

    def test_run_trading_day_fetches_all(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        sample_daily_price_finmind_data,
    ):
        """Trading day: price + 6 chip datasets = 7 API calls total"""
        updater = DailyUpdater()
        updater.fm_loader.taiwan_stock_daily.return_value = (
            sample_daily_price_finmind_data
        )
        # Chip datasets return empty so they don't need pivot etc.
        for method_name, _, _ in CHIP_DATASETS:
            getattr(updater.fm_loader, method_name).return_value = pd.DataFrame()

        updater.run("2023-01-03")

        # Price API called once
        assert updater.fm_loader.taiwan_stock_daily.call_count == 1
        # Each chip method called once
        for method_name, _, _ in CHIP_DATASETS:
            assert getattr(updater.fm_loader, method_name).call_count == 1


# ============================================================================
# TestDailyUpdaterFetchPrice
# ============================================================================


class TestDailyUpdaterFetchPrice:
    """Test DailyUpdater._fetch_price()"""

    def test_fetch_price_success(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        sample_daily_price_finmind_data,
    ):
        """Normal return: columns mapped correctly (max->high, min->low, Trading_Volume->volume)"""
        updater = DailyUpdater()
        updater.fm_loader.taiwan_stock_daily.return_value = (
            sample_daily_price_finmind_data
        )

        result = updater._fetch_price("2023-01-03")
        assert result == "ok"

        # Check save_to_db was called with mapped columns
        saved_df = mock_db_save.call_args[0][0]
        assert "high" in saved_df.columns
        assert "low" in saved_df.columns
        assert "volume" in saved_df.columns
        assert "max" not in saved_df.columns
        assert "min" not in saved_df.columns
        assert "Trading_Volume" not in saved_df.columns

    def test_fetch_price_empty_returns_no_data(
        self, mock_finmind_client, mock_rate_limiter, mock_db_save
    ):
        """FinMind returns empty DataFrame -> return 'no_data'"""
        updater = DailyUpdater()
        updater.fm_loader.taiwan_stock_daily.return_value = pd.DataFrame()

        result = updater._fetch_price("2023-01-01")
        assert result == "no_data"

    def test_fetch_price_none_returns_no_data(
        self, mock_finmind_client, mock_rate_limiter, mock_db_save
    ):
        """FinMind returns None -> return 'no_data'"""
        updater = DailyUpdater()
        updater.fm_loader.taiwan_stock_daily.return_value = None

        result = updater._fetch_price("2023-01-01")
        assert result == "no_data"

    def test_fetch_price_api_exception(
        self, mock_finmind_client, mock_rate_limiter, mock_db_save
    ):
        """API throws exception -> return 'no_data', no crash"""
        updater = DailyUpdater()
        updater.fm_loader.taiwan_stock_daily.side_effect = Exception(
            "API Error"
        )

        result = updater._fetch_price("2023-01-03")
        assert result == "no_data"

    def test_fetch_price_write_error(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        sample_daily_price_finmind_data,
    ):
        """DB write fails -> return 'write_error' (not 'no_data')"""
        updater = DailyUpdater()
        updater.fm_loader.taiwan_stock_daily.return_value = (
            sample_daily_price_finmind_data
        )
        mock_db_save.return_value = False

        result = updater._fetch_price("2023-01-03")
        assert result == "write_error"

    def test_fetch_price_column_selection(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        sample_daily_price_finmind_data,
    ):
        """Only 7 columns kept (date, stock_id, open, high, low, close, volume), extras dropped"""
        updater = DailyUpdater()
        updater.fm_loader.taiwan_stock_daily.return_value = (
            sample_daily_price_finmind_data
        )

        updater._fetch_price("2023-01-03")
        saved_df = mock_db_save.call_args[0][0]

        expected_cols = {"date", "stock_id", "open", "high", "low", "close", "volume"}
        assert set(saved_df.columns) == expected_cols
        # Extra columns like Trading_money, spread should be absent
        assert "Trading_money" not in saved_df.columns
        assert "spread" not in saved_df.columns

    def test_fetch_price_date_conversion(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        sample_daily_price_finmind_data,
    ):
        """date column is converted to date objects"""
        updater = DailyUpdater()
        updater.fm_loader.taiwan_stock_daily.return_value = (
            sample_daily_price_finmind_data
        )

        updater._fetch_price("2023-01-03")
        saved_df = mock_db_save.call_args[0][0]
        assert all(isinstance(d, datetime.date) for d in saved_df["date"])


# ============================================================================
# TestDailyUpdaterFetchChip
# ============================================================================


class TestDailyUpdaterFetchChip:
    """Test DailyUpdater._fetch_chip()"""

    def _make_chip_df(self, date_str="2023-01-03"):
        """Helper: minimal non-empty DataFrame for a chip dataset"""
        return pd.DataFrame({
            "date": [date_str],
            "stock_id": ["2330"],
            "value": [100],
        })

    def test_fetch_chip_all_success(
        self, mock_finmind_client, mock_rate_limiter, mock_db_save
    ):
        """All 6 chip datasets succeed"""
        updater = DailyUpdater()
        for method_name, table_name, _ in CHIP_DATASETS:
            if table_name == "chip_institutional":
                # Institutional needs name/buy/sell for pivot
                getattr(updater.fm_loader, method_name).return_value = pd.DataFrame({
                    "date": ["2023-01-03"],
                    "stock_id": ["2330"],
                    "name": ["Foreign_Investor"],
                    "buy": [100],
                    "sell": [80],
                })
            else:
                getattr(updater.fm_loader, method_name).return_value = (
                    self._make_chip_df()
                )

        results = updater._fetch_chip("2023-01-03")
        assert all(results.values())
        assert len(results) == 6

    def test_fetch_chip_partial_failure(
        self, mock_finmind_client, mock_rate_limiter, mock_db_save
    ):
        """One dataset fails, others still succeed"""
        updater = DailyUpdater()
        datasets = list(CHIP_DATASETS)

        # First dataset (institutional) returns None -> fail
        getattr(updater.fm_loader, datasets[0][0]).return_value = None
        # Remaining datasets return data -> success
        for method_name, table_name, _ in datasets[1:]:
            getattr(updater.fm_loader, method_name).return_value = self._make_chip_df()

        results = updater._fetch_chip("2023-01-03")
        assert results[datasets[0][1]] is False
        for _, table_name, _ in datasets[1:]:
            assert results[table_name] is True

    def test_fetch_chip_institutional_pivot(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        sample_chip_institutional_raw_data,
    ):
        """chip_institutional calls _pivot_institutional() to widen the data"""
        updater = DailyUpdater()
        updater.fm_loader.taiwan_stock_institutional_investors.return_value = (
            sample_chip_institutional_raw_data
        )
        # Other datasets return empty
        for method_name, table_name, _ in CHIP_DATASETS:
            if table_name != "chip_institutional":
                getattr(updater.fm_loader, method_name).return_value = pd.DataFrame()

        results = updater._fetch_chip("2023-01-03")
        assert results["chip_institutional"] is True

        # Verify saved DataFrame has pivot columns, not raw name/buy/sell
        saved_df = mock_db_save.call_args[0][0]
        assert "foreign_investors_buy" in saved_df.columns
        assert "foreign_investors_sell" in saved_df.columns
        assert "investment_trust_buy" in saved_df.columns
        assert "dealer_buy" in saved_df.columns
        assert "name" not in saved_df.columns

    def test_fetch_chip_empty_data(
        self, mock_finmind_client, mock_rate_limiter, mock_db_save
    ):
        """Dataset returns empty DataFrame -> result is False"""
        updater = DailyUpdater()
        for method_name, _, _ in CHIP_DATASETS:
            getattr(updater.fm_loader, method_name).return_value = pd.DataFrame()

        results = updater._fetch_chip("2023-01-03")
        assert all(v is False for v in results.values())

    def test_fetch_chip_api_exception_continues(
        self, mock_finmind_client, mock_rate_limiter, mock_db_save
    ):
        """One dataset throws exception -> continues to next"""
        updater = DailyUpdater()
        datasets = list(CHIP_DATASETS)

        # First dataset raises exception
        getattr(updater.fm_loader, datasets[0][0]).side_effect = Exception("timeout")
        # Second dataset succeeds
        getattr(updater.fm_loader, datasets[1][0]).return_value = self._make_chip_df()
        # Rest return empty
        for method_name, _, _ in datasets[2:]:
            getattr(updater.fm_loader, method_name).return_value = pd.DataFrame()

        results = updater._fetch_chip("2023-01-03")
        assert results[datasets[0][1]] is False
        assert results[datasets[1][1]] is True


# ============================================================================
# TestDailyUpdaterRateLimiting
# ============================================================================


class TestDailyUpdaterRateLimiting:
    """Test that rate limiter wait() is called appropriately"""

    def test_wait_called_after_price(
        self,
        mock_finmind_client,
        mock_rate_limiter,
        mock_db_save,
        sample_daily_price_finmind_data,
    ):
        """limiter.wait() is called after fetching price"""
        updater = DailyUpdater()
        updater.fm_loader.taiwan_stock_daily.return_value = (
            sample_daily_price_finmind_data
        )

        updater._fetch_price("2023-01-03")
        assert updater.limiter.wait.call_count >= 1

    def test_wait_called_after_each_chip(
        self, mock_finmind_client, mock_rate_limiter, mock_db_save
    ):
        """limiter.wait() is called after every chip dataset (even empty ones)"""
        updater = DailyUpdater()
        for method_name, _, _ in CHIP_DATASETS:
            getattr(updater.fm_loader, method_name).return_value = pd.DataFrame()

        updater._fetch_chip("2023-01-03")
        # wait() should be called once per chip dataset = 6 times
        assert updater.limiter.wait.call_count == len(CHIP_DATASETS)
