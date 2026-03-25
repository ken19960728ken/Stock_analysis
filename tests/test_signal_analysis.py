"""
訊號分析工具測試 — 訊號衰減 + 樣本外驗證 + 擁擠度
"""

import numpy as np
import pandas as pd
import pytest

from analysis.strategies.base import Strategy
from analysis.utils.signal_analysis import (
    crowding_backtest,
    oos_validation,
    signal_crowding_analysis,
    signal_decay_report,
)


# ── 測試用 Mock 策略 ──────────────────────────────────


class _BuyLowSellHigh(Strategy):
    name = "test"
    params = {}

    def generate_signals(self, data):
        df = data.copy()
        df["signal"] = 0
        ma = df["close"].rolling(20, min_periods=5).mean()
        df.loc[df["close"] < ma * 0.98, "signal"] = 1
        df.loc[df["close"] > ma * 1.02, "signal"] = -1
        return df


class _AlwaysBuy(Strategy):
    """每天都買"""
    name = "always_buy"
    params = {}

    def generate_signals(self, data):
        df = data.copy()
        df["signal"] = 1
        return df


class _NeverSignal(Strategy):
    """從不發訊號"""
    name = "never"
    params = {}

    def generate_signals(self, data):
        df = data.copy()
        df["signal"] = 0
        return df


class _AlwaysSell(Strategy):
    """每天都賣"""
    name = "always_sell"
    params = {}

    def generate_signals(self, data):
        df = data.copy()
        df["signal"] = -1
        return df


# ── 測試資料生成 ──────────────────────────────────


def _make_test_data(days: int = 200, trend: float = 0.001) -> pd.DataFrame:
    """產生帶趨勢的假資料"""
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=days, freq="B")
    base = 100.0
    returns = np.random.normal(trend, 0.02, days)
    prices = base * np.cumprod(1 + returns)

    return pd.DataFrame({
        "date": dates[:days],
        "open": prices * (1 - np.random.uniform(0, 0.01, days)),
        "high": prices * (1 + np.random.uniform(0, 0.02, days)),
        "low": prices * (1 - np.random.uniform(0, 0.02, days)),
        "close": prices,
        "volume": np.random.randint(1000, 10000, days),
    })


# ── signal_decay_report 測試 ──────────────────────────


class TestSignalDecayReport:

    def test_decay_returns_two_dataframes(self):
        data = _make_test_data()
        strategy = _BuyLowSellHigh()
        detail, summary = signal_decay_report(strategy, data)
        assert isinstance(detail, pd.DataFrame)
        assert isinstance(summary, pd.DataFrame)

    def test_decay_detail_has_horizons(self):
        data = _make_test_data()
        strategy = _BuyLowSellHigh()
        detail, _ = signal_decay_report(strategy, data, horizons=[1, 5, 10])
        if not detail.empty:
            for h in [1, 5, 10]:
                assert f"ret_t{h}" in detail.columns

    def test_decay_summary_has_all_horizons(self):
        data = _make_test_data()
        strategy = _BuyLowSellHigh()
        _, summary = signal_decay_report(strategy, data, horizons=[1, 5, 10, 20])
        if not summary.empty:
            assert set(summary["horizon"].tolist()) == {1, 5, 10, 20}

    def test_decay_hit_rate_range(self):
        data = _make_test_data()
        strategy = _BuyLowSellHigh()
        _, summary = signal_decay_report(strategy, data)
        valid = summary["hit_rate"].dropna()
        if len(valid) > 0:
            assert (valid >= 0).all()
            assert (valid <= 1).all()

    def test_decay_no_signals_returns_empty(self):
        data = _make_test_data()
        strategy = _NeverSignal()
        detail, summary = signal_decay_report(strategy, data)
        assert detail.empty
        assert summary.empty

    def test_decay_with_uptrend_positive_returns(self):
        data = _make_test_data(days=500, trend=0.003)
        strategy = _AlwaysBuy()
        _, summary = signal_decay_report(strategy, data)
        # 強上升趨勢，較長 horizon 的平均報酬應 > 0
        long_horizon = summary[summary["horizon"] == 20]
        if not long_horizon.empty:
            assert long_horizon["mean_return"].iloc[0] > 0


# ── oos_validation 測試 ──────────────────────────


class TestOosValidation:

    def test_oos_returns_dict(self):
        data = _make_test_data(days=300)
        strategy = _BuyLowSellHigh()
        result = oos_validation(strategy, data)
        assert isinstance(result, dict)
        expected_keys = {
            "is_sharpe", "oos_sharpe", "is_return", "oos_return",
            "is_win_rate", "oos_win_rate", "is_trades", "oos_trades",
            "is_period", "oos_period", "decay_rate", "verdict",
        }
        assert expected_keys.issubset(result.keys())

    def test_oos_has_verdict(self):
        data = _make_test_data(days=300)
        strategy = _BuyLowSellHigh()
        result = oos_validation(strategy, data)
        assert result["verdict"] in {"stable", "moderate", "severe", "overfitting"}

    def test_oos_periods_correct(self):
        data = _make_test_data(days=300)
        strategy = _BuyLowSellHigh()
        result = oos_validation(strategy, data)
        is_period = result["is_period"]
        oos_period = result["oos_period"]
        # 兩段不應重疊：is 結束日 < oos 開始日
        if is_period != "N/A" and oos_period != "N/A":
            is_end = is_period.split(" ~ ")[1]
            oos_start = oos_period.split(" ~ ")[0]
            assert is_end <= oos_start

    def test_oos_decay_rate_calculation(self):
        data = _make_test_data(days=300)
        strategy = _BuyLowSellHigh()
        result = oos_validation(strategy, data)
        is_s = result["is_sharpe"]
        oos_s = result["oos_sharpe"]
        if is_s > 0:
            expected = 1.0 - (oos_s / is_s)
            assert abs(result["decay_rate"] - expected) < 1e-9


# ── signal_crowding_analysis 測試 ──────────────────


class TestSignalCrowdingAnalysis:

    def test_crowding_returns_dataframe(self):
        data = _make_test_data()
        strategies = [_BuyLowSellHigh(), _AlwaysBuy()]
        result = signal_crowding_analysis(strategies, data)
        assert isinstance(result, pd.DataFrame)
        expected_cols = {"date", "agree_buy", "agree_sell", "total_strategies",
                         "agreement_ratio", "crowding_level"}
        assert expected_cols.issubset(set(result.columns))

    def test_crowding_agreement_range(self):
        data = _make_test_data()
        strategies = [_BuyLowSellHigh(), _AlwaysBuy(), _AlwaysSell()]
        result = signal_crowding_analysis(strategies, data)
        assert (result["agreement_ratio"] >= 0).all()
        assert (result["agreement_ratio"] <= 1).all()

    def test_crowding_single_strategy(self):
        data = _make_test_data()
        strategies = [_AlwaysBuy()]
        result = signal_crowding_analysis(strategies, data)
        # 單策略：每天 agree_buy=1, total=1, ratio=1.0
        assert (result["agreement_ratio"] == 1.0).all()

    def test_crowding_levels_correct(self):
        data = _make_test_data()
        strategies = [_BuyLowSellHigh(), _AlwaysBuy(), _NeverSignal()]
        result = signal_crowding_analysis(strategies, data)
        valid_levels = {"low", "medium", "high"}
        assert set(result["crowding_level"].unique()).issubset(valid_levels)
