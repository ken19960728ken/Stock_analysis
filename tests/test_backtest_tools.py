"""交易成本敏感度分析 + breakeven_cost 測試"""

import pandas as pd
import pytest

from analysis.strategies.base import Strategy
from analysis.utils.backtest_tools import cost_sensitivity_analysis, breakeven_cost


# ---------------------------------------------------------------------------
# 測試用策略
# ---------------------------------------------------------------------------
class BuyAndHoldStrategy(Strategy):
    """測試用：第 5 天買入，倒數第 5 天賣出"""
    name = "BuyAndHold"
    params = {}

    def generate_signals(self, data):
        df = data.copy()
        df["signal"] = 0
        if len(df) > 10:
            df.iloc[5, df.columns.get_loc("signal")] = 1
            df.iloc[-5, df.columns.get_loc("signal")] = -1
        return df


class LosingStrategy(Strategy):
    """測試用：買高賣低（必虧）"""
    name = "Losing"
    params = {}

    def generate_signals(self, data):
        df = data.copy()
        df["signal"] = 0
        if len(df) > 10:
            # 找最高價位置買入，最低價位置賣出
            high_idx = df["close"].idxmax()
            low_idx = df["close"].idxmin()
            # 確保買入在賣出前
            if high_idx < low_idx:
                high_idx, low_idx = low_idx, high_idx
            df.loc[low_idx, "signal"] = 1   # 買在低點（但 shift 後實際買在下一天）
            df.loc[high_idx, "signal"] = -1  # 賣在高點附近
        return df


def _make_uptrend_data(days=120, start_price=100):
    """產生穩定上漲的假資料"""
    dates = pd.bdate_range("2024-01-02", periods=days)
    prices = [start_price * (1 + 0.002 * i) for i in range(days)]
    return pd.DataFrame({
        "date": dates,
        "open": prices,
        "high": [p * 1.005 for p in prices],
        "low": [p * 0.995 for p in prices],
        "close": prices,
        "volume": [1_000_000] * days,
    })


def _make_downtrend_data(days=120, start_price=100):
    """產生穩定下跌的假資料"""
    dates = pd.bdate_range("2024-01-02", periods=days)
    prices = [start_price * (1 - 0.003 * i) for i in range(days)]
    return pd.DataFrame({
        "date": dates,
        "open": prices,
        "high": [p * 1.005 for p in prices],
        "low": [p * 0.995 for p in prices],
        "close": prices,
        "volume": [1_000_000] * days,
    })


# ---------------------------------------------------------------------------
# 測試 cost_sensitivity_analysis
# ---------------------------------------------------------------------------
class TestCostSensitivity:
    def test_cost_sensitivity_returns_dataframe(self):
        strategy = BuyAndHoldStrategy()
        data = _make_uptrend_data()
        result = cost_sensitivity_analysis(
            strategy, data,
            commission_range=(0.001, 0.002),
            slippage_range=(0.001, 0.005),
        )
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 4  # 2 comm × 2 slip

    def test_cost_sensitivity_higher_cost_lower_return(self):
        strategy = BuyAndHoldStrategy()
        data = _make_uptrend_data()
        result = cost_sensitivity_analysis(
            strategy, data,
            commission_range=(0.001,),
            slippage_range=(0.001, 0.01),
        )
        # 滑價越高，報酬越低
        returns = result.sort_values("slippage")["total_return"].values
        assert returns[0] >= returns[-1]

    def test_cost_sensitivity_column_names(self):
        strategy = BuyAndHoldStrategy()
        data = _make_uptrend_data()
        result = cost_sensitivity_analysis(
            strategy, data,
            commission_range=(0.001425,),
            slippage_range=(0.001,),
        )
        expected_cols = {
            "commission", "slippage", "total_return", "annual_return",
            "sharpe_ratio", "max_drawdown", "win_rate", "trade_count",
            "profit_factor",
        }
        assert set(result.columns) == expected_cols


# ---------------------------------------------------------------------------
# 測試 breakeven_cost
# ---------------------------------------------------------------------------
class TestBreakevenCost:
    def test_breakeven_cost_positive(self):
        strategy = BuyAndHoldStrategy()
        data = _make_uptrend_data()
        be = breakeven_cost(strategy, data)
        assert be > 0

    def test_breakeven_cost_losing_strategy(self):
        """在下跌趨勢中 BuyAndHold 必虧，breakeven 應為 0"""
        strategy = BuyAndHoldStrategy()
        data = _make_downtrend_data()
        be = breakeven_cost(strategy, data)
        assert be == 0.0
