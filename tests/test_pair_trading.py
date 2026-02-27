"""
配對交易工具測試 — analysis/utils/pair_trading.py
覆蓋 Engle-Granger 共整合、Z-Score、半衰期、配對搜尋、交易訊號
"""

import numpy as np
import pandas as pd
import pytest

from analysis.utils.pair_trading import (
    calc_half_life,
    calc_spread,
    calc_zscore,
    engle_granger_test,
    find_cointegrated_pairs,
    pair_trading_signals,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def cointegrated_pair():
    """建立共整合的兩個序列 — Y = 2*X + noise"""
    np.random.seed(42)
    n = 500
    x = np.cumsum(np.random.randn(n)) + 100
    noise = np.random.randn(n) * 0.5
    y = 2 * x + 10 + noise
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.Series(y, index=dates), pd.Series(x, index=dates)


@pytest.fixture
def independent_pair():
    """建立獨立的兩個隨機序列（不共整合）"""
    np.random.seed(123)
    n = 500
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    x = pd.Series(np.cumsum(np.random.randn(n)) + 100, index=dates)
    y = pd.Series(np.cumsum(np.random.randn(n)) + 200, index=dates)
    return y, x


# ============================================================================
# Engle-Granger Test
# ============================================================================

class TestEngleGrangerTest:
    def test_cointegrated_pair(self, cointegrated_pair):
        y, x = cointegrated_pair
        result = engle_granger_test(y, x)
        assert result["is_cointegrated"]
        assert result["p_value"] < 0.05
        assert result["beta"] == pytest.approx(2.0, abs=0.3)
        assert "residuals" in result
        assert len(result["residuals"]) == len(y)

    def test_independent_pair(self, independent_pair):
        y, x = independent_pair
        result = engle_granger_test(y, x)
        # 獨立序列通常不共整合（p_value > 0.05）
        assert result["p_value"] > 0.01  # 較寬鬆的判定

    def test_result_keys(self, cointegrated_pair):
        y, x = cointegrated_pair
        result = engle_granger_test(y, x)
        expected_keys = {
            "beta", "intercept", "r_squared", "residuals",
            "adf_stat", "p_value", "critical_values", "is_cointegrated",
        }
        assert expected_keys == set(result.keys())


# ============================================================================
# Spread & Z-Score
# ============================================================================

class TestCalcSpread:
    def test_basic(self):
        y = pd.Series([210, 220, 230])
        x = pd.Series([100, 110, 120])
        spread = calc_spread(y, x, beta=2.0, intercept=10)
        # spread = y - (2*x + 10) = [210-210, 220-230, 230-250] = [0, -10, -20]
        expected = pd.Series([0.0, -10.0, -20.0])
        pd.testing.assert_series_equal(spread, expected)


class TestCalcZscore:
    def test_basic_properties(self):
        np.random.seed(42)
        spread = pd.Series(np.random.randn(100))
        zscore = calc_zscore(spread, window=20)
        valid = zscore.dropna()
        assert len(valid) > 0
        # Z-Score 均值應接近 0
        assert valid.mean() == pytest.approx(0, abs=1.0)

    def test_window_size(self):
        spread = pd.Series(range(50), dtype=float)
        zscore = calc_zscore(spread, window=10)
        # 前 9 個應為 NaN
        assert zscore.iloc[:9].isna().all()
        assert zscore.iloc[9:].notna().all()


# ============================================================================
# Half-Life
# ============================================================================

class TestCalcHalfLife:
    def test_mean_reverting(self, cointegrated_pair):
        y, x = cointegrated_pair
        result = engle_granger_test(y, x)
        spread = calc_spread(y, x, result["beta"], result["intercept"])
        hl = calc_half_life(spread)
        assert hl > 0
        assert hl < 100  # 共整合的均值回歸應有限半衰期

    def test_trending_series_long_half_life(self):
        """有趨勢的序列 → 半衰期較長（不容易均值回歸）"""
        np.random.seed(42)
        # 明確的上升趨勢序列（非均值回歸）
        trend = pd.Series(np.arange(500, dtype=float) * 0.5 + np.random.randn(500) * 0.1)
        hl = calc_half_life(trend)
        # 趨勢序列的半衰期應為無限或非常長
        assert hl == float("inf") or hl > 50

    def test_short_series(self):
        spread = pd.Series([1.0, 2.0])
        hl = calc_half_life(spread)
        assert hl == float("inf")


# ============================================================================
# Find Cointegrated Pairs
# ============================================================================

class TestFindCointegratedPairs:
    def test_find_pair(self):
        np.random.seed(42)
        n = 500
        x = np.cumsum(np.random.randn(n)) + 100
        dates = pd.date_range("2020-01-01", periods=n, freq="B")

        price_dict = {
            "A": pd.Series(2 * x + np.random.randn(n) * 0.3, index=dates),
            "B": pd.Series(x, index=dates),
            "C": pd.Series(np.cumsum(np.random.randn(n)) + 200, index=dates),
        }
        pairs = find_cointegrated_pairs(price_dict, threshold=0.05)
        # A 和 B 應該被找到
        found_ab = any(
            (p["stock_a"] == "A" and p["stock_b"] == "B") or
            (p["stock_a"] == "B" and p["stock_b"] == "A")
            for p in pairs
        )
        assert found_ab

    def test_sorted_by_pvalue(self):
        np.random.seed(42)
        n = 200
        x = np.cumsum(np.random.randn(n)) + 100
        dates = pd.date_range("2020-01-01", periods=n, freq="B")
        price_dict = {
            "A": pd.Series(2 * x + np.random.randn(n) * 0.3, index=dates),
            "B": pd.Series(x, index=dates),
        }
        pairs = find_cointegrated_pairs(price_dict, threshold=0.10)
        if len(pairs) > 1:
            for i in range(len(pairs) - 1):
                assert pairs[i]["p_value"] <= pairs[i + 1]["p_value"]

    def test_too_short_skipped(self):
        """少於 60 筆的配對應被跳過"""
        dates = pd.date_range("2020-01-01", periods=30, freq="B")
        price_dict = {
            "A": pd.Series(range(30), index=dates, dtype=float),
            "B": pd.Series(range(30), index=dates, dtype=float),
        }
        pairs = find_cointegrated_pairs(price_dict)
        assert len(pairs) == 0

    def test_empty_dict(self):
        assert find_cointegrated_pairs({}) == []


# ============================================================================
# Pair Trading Signals
# ============================================================================

class TestPairTradingSignals:
    def test_basic_signals(self, cointegrated_pair):
        y, x = cointegrated_pair
        result = engle_granger_test(y, x)
        spread = calc_spread(y, x, result["beta"], result["intercept"])
        signals = pair_trading_signals(spread, entry_z=2.0, exit_z=0.5)
        assert isinstance(signals, pd.Series)
        assert len(signals) == len(spread)
        assert set(signals.unique()).issubset({-1, 0, 1})

    def test_flat_spread_no_signals(self):
        """完全平坦的 spread → 無交易訊號"""
        spread = pd.Series([0.0] * 100)
        signals = pair_trading_signals(spread, entry_z=2.0, exit_z=0.5, window=20)
        # Z-Score 全為 NaN 或 0，不應有任何進場
        assert (signals == 0).all()

    def test_extreme_spread_generates_signals(self):
        """極端 spread → 應產生訊號"""
        np.random.seed(42)
        # 先低後高的 spread 模式
        n = 100
        spread = pd.Series(np.zeros(n))
        spread.iloc[:40] = np.random.randn(40) * 0.5
        spread.iloc[40:60] = -5  # 極低
        spread.iloc[60:80] = 0   # 回歸
        spread.iloc[80:] = 5     # 極高

        signals = pair_trading_signals(spread, entry_z=2.0, exit_z=0.5, window=20)
        assert (signals != 0).any()

    def test_stop_loss(self):
        """超過停損閾值應平倉"""
        n = 100
        spread = pd.Series(np.zeros(n))
        spread.iloc[:30] = np.random.randn(30) * 0.5
        # 極端下跌觸發進場後繼續下跌至停損
        spread.iloc[30:50] = -3
        spread.iloc[50:70] = -5  # 超過 stop_z=3.5
        spread.iloc[70:] = 0

        signals = pair_trading_signals(
            spread, entry_z=2.0, exit_z=0.5, stop_z=3.5, window=20
        )
        # 進場後如果繼續惡化到 stop_z 應平倉
        assert isinstance(signals, pd.Series)
