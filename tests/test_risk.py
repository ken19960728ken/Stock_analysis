"""
風險指標計算模組測試 — analysis/utils/risk.py
覆蓋所有 11 個風險函數 + portfolio_risk_report
"""

import numpy as np
import pandas as pd
import pytest

from analysis.utils.risk import (
    calc_alpha,
    calc_beta,
    calc_calmar_ratio,
    calc_cvar,
    calc_information_ratio,
    calc_max_drawdown,
    calc_portfolio_volatility,
    calc_risk_contribution,
    calc_sharpe,
    calc_sortino,
    calc_var,
    portfolio_risk_report,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def daily_returns():
    """250 天模擬日報酬率（正偏態）"""
    np.random.seed(42)
    return pd.Series(np.random.randn(250) * 0.02 + 0.0005)


@pytest.fixture
def negative_returns():
    """持續虧損的報酬率"""
    np.random.seed(42)
    return pd.Series(np.random.randn(250) * 0.02 - 0.005)


@pytest.fixture
def market_returns():
    """大盤日報酬率"""
    np.random.seed(99)
    return pd.Series(np.random.randn(250) * 0.015 + 0.0003)


@pytest.fixture
def equity_curve():
    """權益曲線（先漲後跌再漲）"""
    dates = pd.date_range("2023-01-01", periods=100, freq="B")
    values = [100]
    np.random.seed(42)
    for i in range(99):
        change = np.random.randn() * 2
        if i < 30:
            change += 0.5
        elif i < 60:
            change -= 0.8
        else:
            change += 0.3
        values.append(max(values[-1] + change, 50))
    return pd.Series(values, index=dates)


# ============================================================================
# VaR
# ============================================================================

class TestCalcVaR:
    def test_95_percentile(self, daily_returns):
        var = calc_var(daily_returns, 0.95)
        assert var < 0  # VaR 為負值（損失）

    def test_99_more_extreme(self, daily_returns):
        var95 = calc_var(daily_returns, 0.95)
        var99 = calc_var(daily_returns, 0.99)
        assert var99 <= var95  # 99% VaR 更極端

    def test_empty_returns_zero(self):
        assert calc_var(pd.Series(dtype=float)) == 0.0


# ============================================================================
# CVaR
# ============================================================================

class TestCalcCVaR:
    def test_cvar_worse_than_var(self, daily_returns):
        var = calc_var(daily_returns, 0.95)
        cvar = calc_cvar(daily_returns, 0.95)
        assert cvar <= var  # CVaR (Expected Shortfall) >= VaR in absolute loss

    def test_empty_returns_zero(self):
        assert calc_cvar(pd.Series(dtype=float)) == 0.0


# ============================================================================
# Sharpe Ratio
# ============================================================================

class TestCalcSharpe:
    def test_positive_sharpe(self, daily_returns):
        sharpe = calc_sharpe(daily_returns, rf=0.015)
        assert isinstance(sharpe, float)

    def test_negative_sharpe(self, negative_returns):
        sharpe = calc_sharpe(negative_returns, rf=0.015)
        assert sharpe < 0

    def test_zero_std_returns_zero(self):
        flat = pd.Series([0.0] * 100)
        assert calc_sharpe(flat) == 0.0

    def test_too_few_data(self):
        assert calc_sharpe(pd.Series([0.01])) == 0.0


# ============================================================================
# Sortino Ratio
# ============================================================================

class TestCalcSortino:
    def test_sortino_calculated(self, daily_returns):
        sortino = calc_sortino(daily_returns)
        assert isinstance(sortino, float)

    def test_no_downside_returns_zero(self):
        """全正報酬 downside std = 0"""
        all_positive = pd.Series([0.01, 0.02, 0.03, 0.01])
        assert calc_sortino(all_positive) == 0.0

    def test_too_few_data(self):
        assert calc_sortino(pd.Series([0.01])) == 0.0


# ============================================================================
# Beta
# ============================================================================

class TestCalcBeta:
    def test_self_beta_is_one(self, market_returns):
        """個股 = 大盤時 Beta ≈ 1"""
        beta = calc_beta(market_returns, market_returns)
        assert beta == pytest.approx(1.0, abs=0.01)

    def test_two_series(self, daily_returns, market_returns):
        beta = calc_beta(daily_returns, market_returns)
        assert isinstance(beta, float)

    def test_too_few_data(self):
        assert calc_beta(pd.Series([0.01]), pd.Series([0.02])) == 0.0


# ============================================================================
# Alpha
# ============================================================================

class TestCalcAlpha:
    def test_alpha_calculated(self, daily_returns, market_returns):
        alpha = calc_alpha(daily_returns, market_returns)
        assert isinstance(alpha, float)

    def test_zero_excess_zero_alpha(self, market_returns):
        """個股 = 大盤時 alpha ≈ 0"""
        alpha = calc_alpha(market_returns, market_returns)
        assert alpha == pytest.approx(0.0, abs=0.01)


# ============================================================================
# Max Drawdown
# ============================================================================

class TestCalcMaxDrawdown:
    def test_basic(self, equity_curve):
        max_dd, dd_series, start, end, duration = calc_max_drawdown(equity_curve)
        assert max_dd <= 0
        assert isinstance(dd_series, pd.Series)
        assert start is not None
        assert end is not None
        assert duration >= 0

    def test_monotonic_up_no_drawdown(self):
        """單調上漲無回撤"""
        equity = pd.Series(
            range(100, 200),
            index=pd.date_range("2023-01-01", periods=100, freq="B"),
        )
        max_dd, _, _, _, _ = calc_max_drawdown(equity)
        assert max_dd == 0.0

    def test_empty(self):
        max_dd, _, start, end, dur = calc_max_drawdown(pd.Series(dtype=float))
        assert max_dd == 0.0
        assert start is None


# ============================================================================
# Risk Contribution
# ============================================================================

class TestCalcRiskContribution:
    def test_basic(self):
        weights = np.array([0.5, 0.5])
        cov = pd.DataFrame(
            [[0.04, 0.01], [0.01, 0.09]],
            columns=["A", "B"], index=["A", "B"],
        )
        rc = calc_risk_contribution(weights, cov)
        assert isinstance(rc, pd.Series)
        assert len(rc) == 2
        # 風險貢獻加總 ≈ 組合波動率
        port_vol = np.sqrt(np.dot(weights, np.dot(cov.values, weights)))
        assert rc.sum() == pytest.approx(port_vol, rel=1e-6)

    def test_zero_weights(self):
        weights = np.array([0.0, 0.0])
        cov = pd.DataFrame(
            [[0.04, 0.01], [0.01, 0.09]],
            columns=["A", "B"], index=["A", "B"],
        )
        rc = calc_risk_contribution(weights, cov)
        assert (rc == 0).all()


# ============================================================================
# Portfolio Volatility
# ============================================================================

class TestCalcPortfolioVolatility:
    def test_single_asset(self):
        weights = np.array([1.0])
        cov = pd.DataFrame([[0.04]], columns=["A"], index=["A"])
        vol = calc_portfolio_volatility(weights, cov)
        expected = np.sqrt(0.04 * 252)
        assert vol == pytest.approx(expected, rel=1e-6)

    def test_diversification_effect(self):
        """兩資產低相關 → 組合波動率 < 加權平均波動率"""
        weights = np.array([0.5, 0.5])
        cov = pd.DataFrame(
            [[0.04, 0.005], [0.005, 0.09]],
            columns=["A", "B"], index=["A", "B"],
        )
        vol = calc_portfolio_volatility(weights, cov)
        weighted_avg = 0.5 * np.sqrt(0.04 * 252) + 0.5 * np.sqrt(0.09 * 252)
        assert vol < weighted_avg


# ============================================================================
# Information Ratio
# ============================================================================

class TestCalcInformationRatio:
    def test_basic(self, daily_returns, market_returns):
        ir = calc_information_ratio(daily_returns, market_returns)
        assert isinstance(ir, float)

    def test_same_returns_zero(self, daily_returns):
        ir = calc_information_ratio(daily_returns, daily_returns)
        assert ir == 0.0


# ============================================================================
# Calmar Ratio
# ============================================================================

class TestCalcCalmarRatio:
    def test_basic(self):
        assert calc_calmar_ratio(0.2, -0.1) == pytest.approx(2.0)

    def test_zero_drawdown(self):
        assert calc_calmar_ratio(0.2, 0.0) == 0.0

    def test_negative_return(self):
        assert calc_calmar_ratio(-0.1, -0.3) < 0


# ============================================================================
# Portfolio Risk Report
# ============================================================================

class TestPortfolioRiskReport:
    def test_basic_report(self):
        holdings = pd.DataFrame({
            "stock_id": ["A", "B"],
            "shares": [100, 200],
            "cost_price": [50.0, 30.0],
        })
        np.random.seed(42)
        dates = pd.date_range("2023-01-01", periods=100, freq="B")
        price_a = pd.DataFrame({
            "close": 50 + np.cumsum(np.random.randn(100) * 0.5),
        })
        price_b = pd.DataFrame({
            "close": 30 + np.cumsum(np.random.randn(100) * 0.3),
        })
        price_data = {"A": price_a, "B": price_b}

        report = portfolio_risk_report(holdings, price_data)
        assert "positions" in report
        assert "total_value" in report
        assert "VaR_95" in report
        assert "sharpe" in report

    def test_with_market_returns(self):
        holdings = pd.DataFrame({
            "stock_id": ["A"],
            "shares": [100],
            "cost_price": [50.0],
        })
        np.random.seed(42)
        price_a = pd.DataFrame({
            "close": 50 + np.cumsum(np.random.randn(100) * 0.5),
        })
        market_ret = pd.Series(np.random.randn(100) * 0.01)
        report = portfolio_risk_report(holdings, {"A": price_a}, market_ret)
        assert "beta" in report
        assert "alpha" in report

    def test_empty_price_data(self):
        holdings = pd.DataFrame({
            "stock_id": ["A"],
            "shares": [100],
            "cost_price": [50.0],
        })
        report = portfolio_risk_report(holdings, {})
        assert "total_value" in report
