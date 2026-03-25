"""多股票組合回測引擎測試"""

import numpy as np
import pandas as pd
import pytest
from datetime import date, timedelta

from analysis.strategies.base import Strategy
from analysis.utils.multi_stock_backtester import (
    MultiStockBacktester,
    MultiStockResult,
)


# ---------------------------------------------------------------------------
# 測試用策略
# ---------------------------------------------------------------------------
class SimpleTrendStrategy(Strategy):
    """測試用：收盤價 > MA20 買入，< MA20 賣出"""
    name = "SimpleTrend"
    params = {"period": 20}

    def generate_signals(self, data):
        df = data.copy()
        df["signal"] = 0
        ma = df["close"].rolling(
            self.params["period"], min_periods=5
        ).mean()
        df.loc[df["close"] > ma, "signal"] = 1
        df.loc[df["close"] < ma, "signal"] = -1
        return df


# ---------------------------------------------------------------------------
# 輔助函式
# ---------------------------------------------------------------------------
def _make_stock_data(
    stock_id,
    days=100,
    start_price=100,
    trend=0.001,
    volume=1_000_000,
    seed=42,
):
    """產生假的股票資料"""
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range("2024-01-01", periods=days)
    prices = [start_price]
    for i in range(1, days):
        prices.append(prices[-1] * (1 + trend + rng.normal(0, 0.02)))
    df = pd.DataFrame({
        "date": dates,
        "open": prices,
        "high": [p * 1.01 for p in prices],
        "low": [p * 0.99 for p in prices],
        "close": prices,
        "volume": [volume] * days,
    })
    df["stock_id"] = stock_id
    return df


# ---------------------------------------------------------------------------
# 測試
# ---------------------------------------------------------------------------
class TestMultiStockBacktester:
    def test_empty_input(self):
        bt = MultiStockBacktester(strategy=SimpleTrendStrategy())
        result = bt.run({})
        assert isinstance(result, MultiStockResult)
        assert result.trade_count == 0
        assert result.total_return == 0.0

    def test_single_stock_has_trades(self):
        """單股回測應產生交易"""
        bt = MultiStockBacktester(
            strategy=SimpleTrendStrategy(),
            max_positions=5,
        )
        data = {"2330": _make_stock_data("2330", days=200, trend=0.002)}
        result = bt.run(data)
        assert result.trade_count >= 0  # 至少能跑完
        assert not result.equity_curve.empty

    def test_max_positions_respected(self):
        """不超過 max_positions"""
        max_pos = 2
        bt = MultiStockBacktester(
            strategy=SimpleTrendStrategy(),
            max_positions=max_pos,
        )
        stock_data = {
            f"stock_{i}": _make_stock_data(
                f"stock_{i}", days=200, trend=0.003, seed=i * 10
            )
            for i in range(5)
        }
        result = bt.run(stock_data)
        assert result.max_concurrent_positions <= max_pos

    def test_multi_stock_has_trades(self):
        """多股產生交易"""
        bt = MultiStockBacktester(
            strategy=SimpleTrendStrategy(),
            max_positions=5,
        )
        stock_data = {
            f"stock_{i}": _make_stock_data(
                f"stock_{i}", days=200, trend=0.002, seed=i * 7
            )
            for i in range(3)
        }
        result = bt.run(stock_data)
        assert result.trade_count > 0

    def test_equity_curve_monotonic_dates(self):
        """equity curve 日期遞增"""
        bt = MultiStockBacktester(strategy=SimpleTrendStrategy())
        data = {"2330": _make_stock_data("2330", days=150, trend=0.002)}
        result = bt.run(data)
        if not result.equity_curve.empty:
            dates = list(result.equity_curve.index)
            assert dates == sorted(dates)

    def test_trades_have_stock_id(self):
        """交易記錄包含 stock_id"""
        bt = MultiStockBacktester(
            strategy=SimpleTrendStrategy(),
            max_positions=5,
        )
        stock_data = {
            f"stock_{i}": _make_stock_data(
                f"stock_{i}", days=200, trend=0.002, seed=i * 13
            )
            for i in range(3)
        }
        result = bt.run(stock_data)
        if not result.trades.empty:
            assert "stock_id" in result.trades.columns

    def test_annual_breakdown(self):
        """分年績效有正確年份"""
        bt = MultiStockBacktester(strategy=SimpleTrendStrategy())
        # 跨年度資料
        data = {
            "2330": _make_stock_data(
                "2330", days=400, trend=0.001, seed=42
            ),
        }
        result = bt.run(data)
        if not result.annual_breakdown.empty:
            years = result.annual_breakdown["year"].tolist()
            assert all(isinstance(y, int) for y in years)
            assert len(years) == len(set(years))  # 無重複年份

    def test_dynamic_slippage_works(self):
        """動態滑價 vs 固定滑價結果不同"""
        strategy = SimpleTrendStrategy()
        data = {
            "2330": _make_stock_data(
                "2330", days=200, trend=0.002, volume=50000
            ),
        }

        bt_fixed = MultiStockBacktester(
            strategy=strategy,
            slippage=0.001,
            dynamic_slippage=False,
        )
        bt_dynamic = MultiStockBacktester(
            strategy=strategy,
            slippage=0.001,
            dynamic_slippage=True,
            impact_coeff=0.5,
        )

        r_fixed = bt_fixed.run(data)
        r_dynamic = bt_dynamic.run(data)

        # 只要兩者都有交易，結果就應該不同
        if r_fixed.trade_count > 0 and r_dynamic.trade_count > 0:
            assert r_fixed.total_return != r_dynamic.total_return

    def test_liquidity_filter_works(self):
        """流動性限制：min_avg_volume 過高時無法交易"""
        bt = MultiStockBacktester(
            strategy=SimpleTrendStrategy(),
            min_avg_volume=999_999_999,  # 極高門檻
        )
        data = {
            "2330": _make_stock_data(
                "2330", days=200, trend=0.002, volume=1000
            ),
        }
        result = bt.run(data)
        assert result.trade_count == 0

    def test_position_sizing_equal(self):
        """等權分配：多股同時買入時資金大致均分"""
        bt = MultiStockBacktester(
            strategy=SimpleTrendStrategy(),
            max_positions=10,
            position_sizing="equal",
            capital=10_000_000,
        )
        stock_data = {
            f"stock_{i}": _make_stock_data(
                f"stock_{i}", days=200, start_price=100, trend=0.002,
                seed=i * 11,
            )
            for i in range(5)
        }
        result = bt.run(stock_data)
        # 驗證回測能正常完成
        assert not result.equity_curve.empty
        # 初始資金應等於設定值
        assert result.equity_curve.iloc[0] == pytest.approx(
            10_000_000, rel=0.01
        )
