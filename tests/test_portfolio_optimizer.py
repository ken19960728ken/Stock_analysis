"""
組合最佳化測試 — Max Sharpe / Min Vol / Risk Parity / Black-Litterman
"""

import numpy as np
import pandas as pd
import pytest

from analysis.utils.portfolio_optimizer import (
    OptimizationResult,
    black_litterman,
    efficient_frontier,
    max_sharpe,
    min_volatility,
    risk_parity,
)


@pytest.fixture
def sample_returns():
    """3 資產、100 天日報酬率"""
    np.random.seed(42)
    n = 100
    returns = pd.DataFrame({
        "A": np.random.randn(n) * 0.02 + 0.001,
        "B": np.random.randn(n) * 0.015 + 0.0005,
        "C": np.random.randn(n) * 0.025 + 0.0008,
    })
    return returns


class TestMaxSharpe:
    def test_returns_optimization_result(self, sample_returns):
        result = max_sharpe(sample_returns)
        assert isinstance(result, OptimizationResult)
        assert result.method == "max_sharpe"

    def test_weights_sum_to_one(self, sample_returns):
        result = max_sharpe(sample_returns)
        total = sum(result.weights.values())
        assert abs(total - 1.0) < 0.01

    def test_weights_non_negative(self, sample_returns):
        result = max_sharpe(sample_returns)
        for w in result.weights.values():
            assert w >= -0.01

    def test_has_risk_contributions(self, sample_returns):
        result = max_sharpe(sample_returns)
        assert len(result.risk_contributions) == len(result.weights)

    def test_empty_returns(self):
        result = max_sharpe(pd.DataFrame())
        assert result.method == "max_sharpe"
        assert len(result.weights) == 0


class TestMinVolatility:
    def test_returns_optimization_result(self, sample_returns):
        result = min_volatility(sample_returns)
        assert isinstance(result, OptimizationResult)
        assert result.method == "min_volatility"

    def test_weights_sum_to_one(self, sample_returns):
        result = min_volatility(sample_returns)
        total = sum(result.weights.values())
        assert abs(total - 1.0) < 0.01

    def test_lower_vol_than_equal_weight(self, sample_returns):
        result = min_volatility(sample_returns)
        # 等權波動率
        n = sample_returns.shape[1]
        eq_w = np.ones(n) / n
        cov = sample_returns.cov().values * 252
        eq_vol = np.sqrt(np.dot(eq_w, np.dot(cov, eq_w)))
        assert result.expected_volatility <= eq_vol + 0.01


class TestRiskParity:
    def test_returns_optimization_result(self, sample_returns):
        result = risk_parity(sample_returns)
        assert isinstance(result, OptimizationResult)
        assert result.method == "risk_parity"

    def test_weights_sum_to_one(self, sample_returns):
        result = risk_parity(sample_returns)
        total = sum(result.weights.values())
        assert abs(total - 1.0) < 0.01

    def test_risk_contributions_roughly_equal(self, sample_returns):
        result = risk_parity(sample_returns)
        rc_values = list(result.risk_contributions.values())
        if all(v > 0 for v in rc_values):
            rc_pct = [v / sum(rc_values) for v in rc_values]
            target = 1.0 / len(rc_pct)
            for pct in rc_pct:
                assert abs(pct - target) < 0.15  # 容忍 15% 偏差


class TestBlackLitterman:
    def test_returns_optimization_result(self, sample_returns):
        result = black_litterman(sample_returns)
        assert isinstance(result, OptimizationResult)
        assert result.method == "black_litterman"

    def test_with_views(self, sample_returns):
        views = {"A": 0.10}  # 認為 A 年化超額 10%
        result = black_litterman(sample_returns, views=views)
        assert result.weights.get("A", 0) > 0

    def test_with_market_caps(self, sample_returns):
        caps = {"A": 1e12, "B": 5e11, "C": 2e11}
        result = black_litterman(sample_returns, market_caps=caps)
        assert sum(result.weights.values()) > 0.99

    def test_weights_sum_to_one(self, sample_returns):
        result = black_litterman(sample_returns)
        total = sum(result.weights.values())
        assert abs(total - 1.0) < 0.01


class TestEfficientFrontier:
    def test_returns_dataframe(self, sample_returns):
        ef = efficient_frontier(sample_returns, n_points=10)
        assert isinstance(ef, pd.DataFrame)
        assert "return" in ef.columns
        assert "volatility" in ef.columns

    def test_returns_correct_number_of_points(self, sample_returns):
        ef = efficient_frontier(sample_returns, n_points=10)
        assert len(ef) > 0
        assert len(ef) <= 10

    def test_empty_returns(self):
        ef = efficient_frontier(pd.DataFrame())
        assert ef.empty
