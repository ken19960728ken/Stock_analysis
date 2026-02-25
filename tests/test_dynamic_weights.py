"""
動態權重測試 — rolling_ic_weights, ic_decay_weights, combine_factor_scores
"""

import numpy as np
import pandas as pd
import pytest

from analysis.utils.dynamic_weights import (
    combine_factor_scores,
    ic_decay_weights,
    rolling_ic_weights,
)
from analysis.utils.factor_engine import rolling_ic_mean


@pytest.fixture
def sample_ic_dict():
    """2 因子各 60 天 IC 序列"""
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=60, freq="B")
    return {
        "RSI": pd.DataFrame({
            "date": dates,
            "ic": np.random.randn(60) * 0.05 + 0.03,
        }),
        "MACD": pd.DataFrame({
            "date": dates,
            "ic": np.random.randn(60) * 0.04 + 0.02,
        }),
    }


class TestRollingICWeights:
    def test_output_shape(self, sample_ic_dict):
        result = rolling_ic_weights(sample_ic_dict, lookback=20)
        assert isinstance(result, pd.DataFrame)
        assert "date" in result.columns
        assert "factor_name" in result.columns
        assert "weight" in result.columns

    def test_weights_sum_to_one_per_date(self, sample_ic_dict):
        result = rolling_ic_weights(sample_ic_dict, lookback=20)
        if not result.empty:
            for date, group in result.groupby("date"):
                total = group["weight"].sum()
                if total > 0:
                    assert abs(total - 1.0) < 0.01

    def test_icir_method(self, sample_ic_dict):
        result = rolling_ic_weights(sample_ic_dict, method="icir")
        assert not result.empty

    def test_ic_mean_method(self, sample_ic_dict):
        result = rolling_ic_weights(sample_ic_dict, method="ic_mean")
        assert not result.empty

    def test_ic_decay_method(self, sample_ic_dict):
        result = rolling_ic_weights(sample_ic_dict, method="ic_decay")
        assert not result.empty

    def test_empty_input(self):
        result = rolling_ic_weights({})
        assert result.empty

    def test_min_ic_threshold(self, sample_ic_dict):
        """高門檻可能過濾掉部分因子"""
        result = rolling_ic_weights(sample_ic_dict, min_ic=0.5)
        # 應該有些日期的權重為 0
        assert isinstance(result, pd.DataFrame)


class TestICDecayWeights:
    def test_output_structure(self, sample_ic_dict):
        result = ic_decay_weights(sample_ic_dict, half_life=10)
        assert isinstance(result, pd.DataFrame)
        if not result.empty:
            assert "date" in result.columns
            assert "weight" in result.columns

    def test_empty_input(self):
        result = ic_decay_weights({})
        assert result.empty


class TestCombineFactorScores:
    def test_basic_combination(self):
        scores = {
            "RSI": pd.Series([0.5, 0.3, 0.8], index=["A", "B", "C"]),
            "MACD": pd.Series([0.2, 0.7, 0.4], index=["A", "B", "C"]),
        }
        weights = pd.Series({"RSI": 0.6, "MACD": 0.4})
        result = combine_factor_scores(scores, weights)
        assert len(result) == 3
        expected_A = 0.5 * 0.6 + 0.2 * 0.4
        assert abs(result["A"] - expected_A) < 1e-6

    def test_empty_input(self):
        result = combine_factor_scores({}, pd.Series(dtype=float))
        assert result.empty


class TestRollingICMean:
    def test_output_shape(self):
        ic_df = pd.DataFrame({
            "date": pd.date_range("2023-01-01", periods=60, freq="B"),
            "ic": np.random.randn(60) * 0.05,
        })
        result = rolling_ic_mean(ic_df, window=20)
        assert isinstance(result, pd.Series)
        assert len(result) == 60

    def test_empty_input(self):
        result = rolling_ic_mean(pd.DataFrame(), window=20)
        assert result.empty
