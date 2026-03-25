"""
散戶vs主力反向指標策略測試（8 項）
"""

import numpy as np
import pandas as pd
import pytest

from analysis.strategies import STRATEGY_MAP
from analysis.strategies.retail_vs_institutional import RetailVsInstitutionalStrategy


def _make_data(n: int = 200, with_fields: bool = True) -> pd.DataFrame:
    """產生含 day_trade_volume / foreign_net 的測試 DataFrame"""
    dates = pd.bdate_range("2024-06-01", periods=n)
    np.random.seed(123)
    close = 50 + np.cumsum(np.random.randn(n) * 0.3)
    volume = np.random.randint(1_000_000, 10_000_000, size=n).astype(float)

    data = {
        "date": dates,
        "open": close - 0.3,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": volume,
    }

    if with_fields:
        # 當沖量：預設為 volume 的 20%（中性）
        day_trade_volume = volume * 0.20
        # 區間 100~110: 當沖比例極低（散戶冷）
        day_trade_volume[100:111] = volume[100:111] * 0.02
        # 區間 150~160: 當沖比例極高（散戶熱）
        day_trade_volume[150:161] = volume[150:161] * 0.60
        data["day_trade_volume"] = day_trade_volume

        # 外資淨買超
        foreign_net = np.random.randn(n) * 5000
        # 區間 100~110: 外資連續買超
        foreign_net[100:111] = np.abs(foreign_net[100:111]) + 30000
        # 區間 150~160: 外資連續賣超
        foreign_net[150:161] = -(np.abs(foreign_net[150:161]) + 30000)
        data["foreign_net"] = foreign_net

    return pd.DataFrame(data)


class TestRetailVsInstitutional:
    def test_no_data_returns_no_signal(self):
        """缺少 day_trade_volume 或 foreign_net 時 signal 全 0"""
        # 缺少 day_trade_volume
        df = _make_data(with_fields=False)
        strategy = RetailVsInstitutionalStrategy()
        result = strategy.generate_signals(df)
        assert (result["signal"] == 0).all()

        # 有 day_trade_volume 但缺少 foreign_net
        df2 = _make_data(with_fields=False)
        df2["day_trade_volume"] = df2["volume"] * 0.1
        result2 = strategy.generate_signals(df2)
        assert (result2["signal"] == 0).all()

    def test_buy_on_cold_retail_hot_foreign(self):
        """低 Z-Score + 外資買超 -> 買入"""
        df = _make_data()
        strategy = RetailVsInstitutionalStrategy()
        strategy.params["oversold_z"] = -0.5  # 放寬門檻讓訊號更容易觸發
        strategy.params["foreign_consecutive"] = 3
        result = strategy.generate_signals(df)
        # 區間 100~110 散戶冷 + 外資買，應有買入
        buy_region = result["signal"].iloc[100:115]
        assert (buy_region == 1).any(), "散戶冷+外資買區間應有買入訊號"

    def test_sell_on_hot_retail_cold_foreign(self):
        """高 Z-Score + 外資賣超 -> 賣出"""
        df = _make_data()
        strategy = RetailVsInstitutionalStrategy()
        strategy.params["overbought_z"] = 0.5  # 放寬門檻
        strategy.params["foreign_consecutive"] = 3
        strategy.params["max_hold_days"] = 0  # 關閉 max_hold 以觀察原始訊號
        result = strategy.generate_signals(df)
        # 區間 150~160 散戶熱 + 外資賣，應有賣出
        sell_region = result["signal"].iloc[150:165]
        assert (sell_region == -1).any(), "散戶熱+外資賣區間應有賣出訊號"

    def test_no_signal_in_ambiguous_quadrant(self):
        """散戶冷+外資賣 -> 無明確訊號"""
        df = _make_data()
        # 散戶冷但外資也賣
        df["day_trade_volume"] = df["volume"] * 0.02  # 全程散戶冷
        df["foreign_net"] = -(np.abs(np.random.randn(len(df))) + 10000)  # 全程外資賣
        strategy = RetailVsInstitutionalStrategy()
        strategy.params["max_hold_days"] = 0
        result = strategy.generate_signals(df)
        # 散戶冷 + 外資賣不應有買入（沒有 buy 象限）
        assert (result["signal"] != 1).all(), "散戶冷+外資賣不應有買入訊號"

    def test_max_hold_days(self):
        """最大持有天數"""
        df = _make_data()
        strategy = RetailVsInstitutionalStrategy()
        strategy.params["max_hold_days"] = 5
        strategy.params["oversold_z"] = -0.5
        strategy.params["foreign_consecutive"] = 3
        result = strategy.generate_signals(df)
        buys = result.index[result["signal"] == 1].tolist()
        sells = result.index[result["signal"] == -1].tolist()
        if buys and sells:
            first_buy = buys[0]
            later_sells = [s for s in sells if s > first_buy]
            if later_sells:
                hold_days = later_sells[0] - first_buy
                assert hold_days <= 5, f"持有天數 {hold_days} 超過 max_hold=5"

    def test_zscore_needs_enough_history(self):
        """前 N 天無訊號（窗口不足）"""
        df = _make_data()
        strategy = RetailVsInstitutionalStrategy()
        strategy.params["zscore_window"] = 60
        strategy.params["max_hold_days"] = 0
        result = strategy.generate_signals(df)
        # 前 20 天（min_periods）應無訊號
        early = result["signal"].iloc[:20]
        assert (early == 0).all(), "Z-Score 窗口不足的前期不應有訊號"

    def test_strategy_registered(self):
        """在 STRATEGY_MAP 中"""
        assert "散戶vs主力" in STRATEGY_MAP
        assert STRATEGY_MAP["散戶vs主力"] is RetailVsInstitutionalStrategy

    def test_params_default(self):
        """預設參數正確"""
        s = RetailVsInstitutionalStrategy()
        assert s.params["zscore_window"] == 60
        assert s.params["overbought_z"] == 1.5
        assert s.params["oversold_z"] == -1.0
        assert s.params["foreign_consecutive"] == 3
        assert s.params["max_hold_days"] == 15
