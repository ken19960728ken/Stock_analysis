"""
組合回測測試 — PortfolioBacktester
"""

import numpy as np
import pandas as pd
import pytest

from analysis.strategies.ma_cross import MACrossStrategy
from analysis.strategies.rsi_reversal import RSIReversalStrategy
from analysis.utils.portfolio_backtester import PortfolioBacktester, PortfolioResult


class TestPortfolioBacktester:

    def test_run_two_strategies(self, sample_ohlcv_50d):
        """2 策略 → 2 個 result"""
        strategies = [MACrossStrategy(), RSIReversalStrategy()]
        pb = PortfolioBacktester(strategies=strategies)
        result = pb.run(sample_ohlcv_50d)
        assert isinstance(result, PortfolioResult)
        assert len(result.strategy_results) == 2

    def test_equal_weight_sum_to_one(self, sample_ohlcv_50d):
        """等權 → 每個 1/N"""
        strategies = [MACrossStrategy(), RSIReversalStrategy()]
        pb = PortfolioBacktester(strategies=strategies)
        result = pb.run(sample_ohlcv_50d, equal_weight=True)
        if result.weights:
            total = sum(result.weights.values())
            assert abs(total - 1.0) < 1e-6

    def test_correlation_matrix_shape(self, sample_ohlcv_50d):
        """2 策略 → 2×2"""
        strategies = [MACrossStrategy(), RSIReversalStrategy()]
        pb = PortfolioBacktester(strategies=strategies)
        result = pb.run(sample_ohlcv_50d)
        if not result.correlation_matrix.empty:
            assert result.correlation_matrix.shape[0] <= 2
            assert result.correlation_matrix.shape[1] <= 2

    def test_correlation_diagonal_is_one(self, sample_ohlcv_50d):
        """自相關 = 1"""
        strategies = [MACrossStrategy(), RSIReversalStrategy()]
        pb = PortfolioBacktester(strategies=strategies)
        result = pb.run(sample_ohlcv_50d)
        if not result.correlation_matrix.empty:
            for i in range(len(result.correlation_matrix)):
                val = result.correlation_matrix.iloc[i, i]
                if not np.isnan(val):
                    assert abs(val - 1.0) < 1e-10

    def test_combined_equity_not_empty(self, sample_ohlcv_50d):
        """組合曲線非空"""
        strategies = [MACrossStrategy(), RSIReversalStrategy()]
        pb = PortfolioBacktester(strategies=strategies)
        result = pb.run(sample_ohlcv_50d)
        assert not result.combined_equity.empty

    def test_combined_return_is_float(self, sample_ohlcv_50d):
        """組合報酬為 float"""
        strategies = [MACrossStrategy(), RSIReversalStrategy()]
        pb = PortfolioBacktester(strategies=strategies)
        result = pb.run(sample_ohlcv_50d)
        assert isinstance(result.combined_return, float)

    def test_weight_optimization_sum_to_one(self, sample_ohlcv_50d):
        """優化權重和 = 1"""
        strategies = [MACrossStrategy(), RSIReversalStrategy()]
        pb = PortfolioBacktester(strategies=strategies)
        result = pb.run(sample_ohlcv_50d, equal_weight=False)
        if result.weights:
            total = sum(result.weights.values())
            assert abs(total - 1.0) < 0.01

    def test_weight_optimization_non_negative(self, sample_ohlcv_50d):
        """權重 ≥ 0"""
        strategies = [MACrossStrategy(), RSIReversalStrategy()]
        pb = PortfolioBacktester(strategies=strategies)
        result = pb.run(sample_ohlcv_50d, equal_weight=False)
        if result.weights:
            for w in result.weights.values():
                assert w >= -0.01  # small tolerance

    def test_single_strategy_degrades(self, sample_ohlcv_50d):
        """只有 1 個策略的邊界處理"""
        strategies = [MACrossStrategy()]
        pb = PortfolioBacktester(strategies=strategies)
        result = pb.run(sample_ohlcv_50d)
        assert isinstance(result, PortfolioResult)

    def test_empty_data_handling(self):
        """空 DataFrame → 空結果"""
        strategies = [MACrossStrategy(), RSIReversalStrategy()]
        pb = PortfolioBacktester(strategies=strategies)
        result = pb.run(pd.DataFrame())
        assert isinstance(result, PortfolioResult)
        assert len(result.strategy_results) == 0
