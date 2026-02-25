"""
事件研究測試 — extract_events, calc_abnormal_returns, event_trading_signals
"""

import numpy as np
import pandas as pd
import pytest

from analysis.utils.event_study import (
    EventStudyResult,
    calc_abnormal_returns,
    event_trading_signals,
    extract_events,
)


@pytest.fixture
def sample_dividend_events():
    return pd.DataFrame({
        "stock_id": ["2330", "2330", "2317"],
        "date": pd.to_datetime(["2023-06-15", "2023-12-15", "2023-07-20"]),
        "dividend": [10.0, 6.0, 5.0],
    })


@pytest.fixture
def sample_earnings_events():
    return pd.DataFrame({
        "stock_id": ["2330", "2317"],
        "date": pd.to_datetime(["2023-03-31", "2023-06-30"]),
        "eps_value": [8.5, 3.2],
    })


@pytest.fixture
def sample_price_df():
    """2 支股票、200 天日K"""
    dates = pd.date_range("2023-01-01", periods=200, freq="B")
    np.random.seed(42)
    rows = []
    for sid, base in [("2330", 500), ("2317", 100)]:
        prices = base + np.cumsum(np.random.randn(200) * 2)
        for i, d in enumerate(dates):
            rows.append({
                "stock_id": sid,
                "date": d,
                "close": float(prices[i]),
                "open": float(prices[i] - 1),
                "high": float(prices[i] + 2),
                "low": float(prices[i] - 2),
                "volume": 30_000_000,
            })
    return pd.DataFrame(rows)


class TestExtractEvents:
    def test_dividend_extraction(self, sample_dividend_events):
        result = extract_events(sample_dividend_events, "dividend")
        assert len(result) == 3
        assert "stock_id" in result.columns
        assert "event_date" in result.columns
        assert "event_value" in result.columns

    def test_earnings_extraction(self, sample_earnings_events):
        result = extract_events(sample_earnings_events, "earnings")
        assert len(result) == 2

    def test_empty_input(self):
        result = extract_events(pd.DataFrame(), "dividend")
        assert result.empty

    def test_unknown_type_raises(self, sample_dividend_events):
        with pytest.raises(ValueError):
            extract_events(sample_dividend_events, "unknown")


class TestCalcAbnormalReturns:
    def test_returns_event_study_result(self, sample_price_df, sample_dividend_events):
        events = extract_events(sample_dividend_events, "dividend")
        result = calc_abnormal_returns(sample_price_df, events)
        assert isinstance(result, EventStudyResult)

    def test_has_car_and_aar(self, sample_price_df, sample_dividend_events):
        events = extract_events(sample_dividend_events, "dividend")
        result = calc_abnormal_returns(
            sample_price_df, events, window_before=5, window_after=10
        )
        if result.stats.get("n_events", 0) > 0:
            assert not result.car.empty
            assert not result.aar.empty

    def test_market_adjusted_model(self, sample_price_df, sample_dividend_events):
        events = extract_events(sample_dividend_events, "dividend")
        result = calc_abnormal_returns(
            sample_price_df, events, model="market_adjusted"
        )
        assert isinstance(result, EventStudyResult)

    def test_mean_return_model(self, sample_price_df, sample_dividend_events):
        events = extract_events(sample_dividend_events, "dividend")
        result = calc_abnormal_returns(
            sample_price_df, events, model="mean_return"
        )
        assert isinstance(result, EventStudyResult)

    def test_empty_events(self, sample_price_df):
        result = calc_abnormal_returns(
            sample_price_df, pd.DataFrame(columns=["stock_id", "event_date", "event_value"])
        )
        assert isinstance(result, EventStudyResult)

    def test_empty_prices(self, sample_dividend_events):
        events = extract_events(sample_dividend_events, "dividend")
        result = calc_abnormal_returns(pd.DataFrame(), events)
        assert isinstance(result, EventStudyResult)

    def test_stats_has_n_events(self, sample_price_df, sample_dividend_events):
        events = extract_events(sample_dividend_events, "dividend")
        result = calc_abnormal_returns(sample_price_df, events)
        assert "n_events" in result.stats


class TestEventTradingSignals:
    def test_adds_signal_column(self, sample_price_df, sample_dividend_events):
        events = extract_events(sample_dividend_events, "dividend")
        result = event_trading_signals(events, sample_price_df)
        assert "signal" in result.columns

    def test_has_buy_and_sell_signals(self, sample_price_df, sample_dividend_events):
        events = extract_events(sample_dividend_events, "dividend")
        result = event_trading_signals(events, sample_price_df)
        assert (result["signal"] == 1).any()
        assert (result["signal"] == -1).any()

    def test_empty_events(self, sample_price_df):
        result = event_trading_signals(
            pd.DataFrame(columns=["stock_id", "event_date", "event_value"]),
            sample_price_df,
        )
        assert "signal" in result.columns
        assert (result["signal"] == 0).all()

    def test_custom_window(self, sample_price_df, sample_dividend_events):
        events = extract_events(sample_dividend_events, "dividend")
        result = event_trading_signals(events, sample_price_df,
                                       entry_before=3, exit_after=5)
        assert "signal" in result.columns
