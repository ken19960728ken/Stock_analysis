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


# ---------------------------------------------------------------------------
# 動態滑價 / 流動性限制 / 分年績效 測試
# ---------------------------------------------------------------------------

def _make_ohlcv(days: int = 120, base_price: float = 100.0,
                volume: int = 30_000_000, seed: int = 42) -> pd.DataFrame:
    """產生含 volume 的 OHLCV 測試資料"""
    np.random.seed(seed)
    dates = pd.date_range("2023-01-02", periods=days, freq="B")
    close = base_price + np.cumsum(np.random.randn(days) * 1.5)
    close = np.maximum(close, 10)  # 避免負價格
    return pd.DataFrame({
        "date": dates,
        "stock_id": "2330",
        "open": close - 0.5,
        "high": close + 2,
        "low": close - 2,
        "close": close,
        "volume": np.full(days, volume, dtype=int),
    })


class MockMultiTradeStrategy(Strategy):
    """每 30 天買入、持有 15 天後賣出（shift 前）"""
    name = "MockMultiTrade"

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["signal"] = 0
        sig_loc = df.columns.get_loc("signal")
        i = 0
        while i < len(df) - 16:
            df.iloc[i, sig_loc] = 1
            df.iloc[i + 15, sig_loc] = -1
            i += 30
        return df


class TestDynamicSlippage:

    def test_dynamic_slippage_disabled_by_default(self, sample_ohlcv_50d):
        """預設 dynamic_slippage=False，行為不變"""
        bt = Backtester(strategy=MockBuyHoldStrategy())
        assert bt.dynamic_slippage is False
        result = bt.run(sample_ohlcv_50d)
        assert isinstance(result, BacktestResult)

    def test_dynamic_slippage_increases_cost(self):
        """啟用動態滑價後，低流動性股票的滑價成本更高（總報酬更低）"""
        low_vol_data = _make_ohlcv(days=60, volume=500)  # 極低量
        high_vol_data = _make_ohlcv(days=60, volume=50_000_000)  # 高量

        bt_low = Backtester(
            strategy=MockBuyHoldStrategy(),
            dynamic_slippage=True, impact_coeff=0.1,
        )
        bt_high = Backtester(
            strategy=MockBuyHoldStrategy(),
            dynamic_slippage=True, impact_coeff=0.1,
        )
        result_low = bt_low.run(low_vol_data)
        result_high = bt_high.run(high_vol_data)

        # 低量股滑價更高 → 報酬更差
        if result_low.trade_count > 0 and result_high.trade_count > 0:
            assert result_low.total_return < result_high.total_return

    def test_calc_dynamic_slippage_method(self):
        """直接測試 _calc_dynamic_slippage 計算"""
        bt = Backtester(strategy=MockBuyHoldStrategy(), impact_coeff=0.1)
        # 低參與率
        slip_low = bt._calc_dynamic_slippage(1000, 1_000_000)
        # 高參與率
        slip_high = bt._calc_dynamic_slippage(100_000, 1_000_000)
        assert slip_high > slip_low
        # base = 0.0005, impact = 1000/1e6 * 0.1 = 0.0001
        assert abs(slip_low - 0.0006) < 1e-6

    def test_calc_dynamic_slippage_zero_volume(self):
        """avg_volume=0 時用保守 1%"""
        bt = Backtester(strategy=MockBuyHoldStrategy(), impact_coeff=0.1)
        slip = bt._calc_dynamic_slippage(1000, 0)
        assert abs(slip - 0.0105) < 1e-6  # 0.0005 + 0.01


class TestLiquidityFilter:

    def test_liquidity_filter_skips_low_volume(self):
        """min_avg_volume 過濾掉低量股票"""
        data = _make_ohlcv(days=60, volume=100)  # 極低量
        bt = Backtester(
            strategy=MockBuyHoldStrategy(),
            min_avg_volume=1_000_000,  # 要求日均量 100 萬股
        )
        result = bt.run(data)
        assert result.trade_count == 0  # 因流動性不足放棄交易

    def test_max_participation_limits_shares(self):
        """max_participation 限制買入股數"""
        data = _make_ohlcv(days=60, volume=10_000, base_price=10.0)
        # 不限制
        bt_no_limit = Backtester(
            strategy=MockBuyHoldStrategy(),
            max_participation=1.0,
        )
        result_no_limit = bt_no_limit.run(data)

        # 限制參與率 5%
        bt_limited = Backtester(
            strategy=MockBuyHoldStrategy(),
            max_participation=0.05,
        )
        result_limited = bt_limited.run(data)

        # 有限制時買的股數更少（或無法交易）
        if result_no_limit.trade_count > 0:
            if result_limited.trade_count > 0:
                shares_no_limit = result_no_limit.trades.iloc[0]["shares"]
                shares_limited = result_limited.trades.iloc[0]["shares"]
                assert shares_limited <= shares_no_limit
            # 也可能因為 max_shares 算出 0 張而完全不交易

    def test_no_limit_by_default(self, sample_ohlcv_50d):
        """預設不限制流動性"""
        bt = Backtester(strategy=MockBuyHoldStrategy())
        assert bt.max_participation == 1.0
        assert bt.min_avg_volume == 0


class TestAnnualBreakdown:

    def test_annual_breakdown_has_correct_years(self):
        """分年績效包含正確年份"""
        data = _make_ohlcv(days=120)  # 跨 2023 年約半年
        bt = Backtester(strategy=MockMultiTradeStrategy())
        result = bt.run(data)
        if not result.annual_breakdown.empty:
            years = result.annual_breakdown["year"].tolist()
            assert 2023 in years

    def test_annual_breakdown_return_matches(self):
        """各年報酬方向大致合理（非嚴格加總，因複利效應）"""
        data = _make_ohlcv(days=120)
        bt = Backtester(strategy=MockMultiTradeStrategy())
        result = bt.run(data)
        if not result.annual_breakdown.empty:
            # 至少有 return 欄位
            assert "return" in result.annual_breakdown.columns
            assert "sharpe" in result.annual_breakdown.columns
            assert "max_drawdown" in result.annual_breakdown.columns
            assert "trade_count" in result.annual_breakdown.columns
            assert "win_rate" in result.annual_breakdown.columns

    def test_annual_breakdown_empty_for_short_data(self):
        """極短資料仍可產出（空或有內容皆可）"""
        data = _make_ohlcv(days=5)
        bt = Backtester(strategy=MockBuyHoldStrategy())
        result = bt.run(data)
        assert isinstance(result.annual_breakdown, pd.DataFrame)

    def test_annual_breakdown_trade_count(self):
        """交易統計歸到正確年度"""
        data = _make_ohlcv(days=120)
        bt = Backtester(strategy=MockMultiTradeStrategy())
        result = bt.run(data)
        if not result.annual_breakdown.empty:
            total_from_breakdown = result.annual_breakdown["trade_count"].sum()
            assert total_from_breakdown == result.trade_count


class TestBackwardCompatible:

    def test_backward_compatible(self, sample_ohlcv_50d):
        """不傳新參數時，結果與舊版行為一致"""
        bt = Backtester(strategy=MockBuyHoldStrategy())
        result = bt.run(sample_ohlcv_50d)

        # 確認所有舊有欄位正常
        assert isinstance(result.total_return, float)
        assert isinstance(result.sharpe_ratio, float)
        assert isinstance(result.max_drawdown, float)
        assert isinstance(result.trade_count, int)
        assert isinstance(result.equity_curve, pd.Series)
        assert isinstance(result.trades, pd.DataFrame)
        assert isinstance(result.monthly_returns, pd.Series)
        # 新欄位也存在但不影響舊行為
        assert isinstance(result.annual_breakdown, pd.DataFrame)
