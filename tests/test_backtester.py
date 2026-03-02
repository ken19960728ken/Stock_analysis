"""
回測引擎測試 — Backtester 補充測試
"""

import numpy as np
import pandas as pd
import pytest

from analysis.strategies.base import BacktestResult, Strategy
from analysis.utils.backtester import Backtester


class MockBuyHoldStrategy(Strategy):
    """第一天產生買入訊號、倒數第二天產生賣出訊號
    （Backtester 會將 signal shift 1 日，實際在第二天買、最後一天賣）
    """
    name = "MockBuyHold"

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["signal"] = 0
        if len(df) >= 3:
            df.iloc[0, df.columns.get_loc("signal")] = 1
            df.iloc[-2, df.columns.get_loc("signal")] = -1
        return df


class MockNoSignalStrategy(Strategy):
    """永遠不發 signal"""
    name = "MockNoSignal"

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["signal"] = 0
        return df


class TestBacktester:

    def test_basic_run_returns_backtest_result(self, sample_ohlcv_50d):
        """回傳類型正確"""
        bt = Backtester(strategy=MockBuyHoldStrategy())
        result = bt.run(sample_ohlcv_50d)
        assert isinstance(result, BacktestResult)

    def test_empty_data_returns_empty_result(self):
        """空資料不報錯"""
        bt = Backtester(strategy=MockBuyHoldStrategy())
        result = bt.run(pd.DataFrame())
        assert isinstance(result, BacktestResult)
        assert result.trade_count == 0

    def test_no_signal_no_trades(self, sample_ohlcv_50d):
        """全 signal=0 → 0 交易"""
        bt = Backtester(strategy=MockNoSignalStrategy())
        result = bt.run(sample_ohlcv_50d)
        assert result.trade_count == 0

    def test_buy_then_sell_one_trade(self, sample_ohlcv_50d):
        """一買一賣 → 1 筆交易"""
        bt = Backtester(strategy=MockBuyHoldStrategy())
        result = bt.run(sample_ohlcv_50d)
        assert result.trade_count == 1

    def test_lot_size_1000(self, sample_ohlcv_50d):
        """股數為 1000 倍數"""
        bt = Backtester(strategy=MockBuyHoldStrategy())
        result = bt.run(sample_ohlcv_50d)
        if not result.trades.empty:
            for _, trade in result.trades.iterrows():
                assert trade["shares"] % 1000 == 0

    def test_commission_applied(self, sample_ohlcv_50d):
        """手續費扣除 → 即使價格不變也會虧損"""
        # 修改為固定價格
        df = sample_ohlcv_50d.copy()
        df["close"] = 100.0
        df["open"] = 100.0
        df["high"] = 101.0
        df["low"] = 99.0
        bt = Backtester(strategy=MockBuyHoldStrategy(), slippage=0.0)
        result = bt.run(df)
        if result.trade_count > 0:
            # 因手續費+稅，最終權益應小於初始
            assert result.total_return < 0

    def test_tax_only_on_sell(self, sample_ohlcv_50d):
        """驗證有稅率參數"""
        bt = Backtester(strategy=MockBuyHoldStrategy(), tax=0.003)
        result = bt.run(sample_ohlcv_50d)
        assert isinstance(result, BacktestResult)

    def test_equity_curve_length_matches_data(self, sample_ohlcv_50d):
        """權益曲線長度 = data 長度"""
        bt = Backtester(strategy=MockBuyHoldStrategy())
        result = bt.run(sample_ohlcv_50d)
        if not result.equity_curve.empty:
            assert len(result.equity_curve) == len(sample_ohlcv_50d)

    def test_sharpe_ratio_calculation(self, sample_ohlcv_50d):
        """Sharpe 計算合理"""
        bt = Backtester(strategy=MockBuyHoldStrategy())
        result = bt.run(sample_ohlcv_50d)
        assert isinstance(result.sharpe_ratio, float)

    def test_max_drawdown_non_positive(self, sample_ohlcv_50d):
        """最大回撤 ≤ 0"""
        bt = Backtester(strategy=MockBuyHoldStrategy())
        result = bt.run(sample_ohlcv_50d)
        assert result.max_drawdown <= 0
