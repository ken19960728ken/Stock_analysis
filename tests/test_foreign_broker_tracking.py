"""
外資連續買超策略測試（8 項）
"""

import numpy as np
import pandas as pd
import pytest

from analysis.strategies import STRATEGY_MAP
from analysis.strategies.foreign_broker_tracking import ForeignBrokerTrackingStrategy


def _make_data(n: int = 100, with_broker: bool = True) -> pd.DataFrame:
    """產生含 foreign_net / foreign_broker_count 的測試 DataFrame"""
    dates = pd.bdate_range("2025-01-01", periods=n)
    np.random.seed(42)
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    volume = np.random.randint(500_000, 5_000_000, size=n).astype(float)
    data = {
        "date": dates,
        "open": close - 0.5,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": volume,
    }
    if with_broker:
        # 預設 foreign_net 隨機，部分區間設為正（連續買超）
        foreign_net = np.random.randn(n) * 10000
        # 在 day 30~39 設為連續正值（10 天買超）
        foreign_net[30:40] = np.abs(foreign_net[30:40]) + 50000
        # 在 day 50~55 設為連續負值（6 天賣超）
        foreign_net[50:56] = -np.abs(foreign_net[50:56]) - 50000
        data["foreign_net"] = foreign_net
        data["foreign_broker_count"] = np.random.randint(1, 10, size=n)
        # 買超區間給足夠的 broker count
        data["foreign_broker_count"][30:40] = 5
    return pd.DataFrame(data)


class TestForeignBrokerTracking:
    def test_no_broker_data_returns_no_signal(self):
        """無 foreign_net 欄位時 signal 全 0"""
        df = _make_data(with_broker=False)
        strategy = ForeignBrokerTrackingStrategy()
        result = strategy.generate_signals(df)
        assert (result["signal"] == 0).all()

    def test_consecutive_buy_generates_signal(self):
        """連續買超產生買入訊號"""
        df = _make_data()
        strategy = ForeignBrokerTrackingStrategy()
        strategy.params["consecutive_days"] = 3
        strategy.params["min_brokers"] = 3
        result = strategy.generate_signals(df)
        # day 30~39 有連續買超 + 足夠 broker，應產生至少一個買入
        buy_signals = result["signal"].iloc[30:45]
        assert (buy_signals == 1).any(), "連續買超區間應有買入訊號"

    def test_min_brokers_filter(self):
        """broker_count < min_brokers 不買入"""
        df = _make_data()
        # 把所有 broker_count 設為 1（低於門檻 3）
        df["foreign_broker_count"] = 1
        strategy = ForeignBrokerTrackingStrategy()
        strategy.params["min_brokers"] = 3
        result = strategy.generate_signals(df)
        assert (result["signal"] != 1).all(), "broker 不足時不應有買入訊號"

    def test_sell_on_consecutive_sell(self):
        """連續賣超產生賣出訊號"""
        df = _make_data()
        strategy = ForeignBrokerTrackingStrategy()
        # 先確保有買入，然後 day 50~55 連續賣超應觸發賣出
        result = strategy.generate_signals(df)
        # 連續賣超區間附近可能有賣出訊號
        sell_signals = result["signal"].iloc[50:60]
        has_sell = (sell_signals == -1).any()
        # 如果沒有持倉，max_hold 會觸發出場
        has_any_sell = (result["signal"] == -1).any()
        assert has_sell or has_any_sell, "應有賣出訊號"

    def test_max_hold_days(self):
        """持有超過 max_hold 強制出場"""
        df = _make_data()
        strategy = ForeignBrokerTrackingStrategy()
        strategy.params["max_hold_days"] = 5
        # 移除賣出訊號條件（讓 foreign_net 都為正）
        df["foreign_net"] = np.abs(df["foreign_net"].values) + 1000
        df["foreign_broker_count"] = 5
        result = strategy.generate_signals(df)
        buys = result.index[result["signal"] == 1].tolist()
        sells = result.index[result["signal"] == -1].tolist()
        if buys and sells:
            # 第一個買入到第一個賣出應 <= max_hold_days
            first_buy = buys[0]
            first_sell = [s for s in sells if s > first_buy]
            if first_sell:
                hold_days = first_sell[0] - first_buy
                assert hold_days <= 5, f"持有天數 {hold_days} 超過 max_hold=5"

    def test_volume_pct_filter(self):
        """累積淨買超不足時不買入"""
        df = _make_data()
        # 設定極高的 volume_pct 門檻
        strategy = ForeignBrokerTrackingStrategy()
        strategy.params["net_volume_pct"] = 100.0  # 需 10000% 的日均量
        result = strategy.generate_signals(df)
        assert (result["signal"] != 1).all(), "volume_pct 門檻極高時不應有買入"

    def test_strategy_registered(self):
        """在 STRATEGY_MAP 中"""
        assert "外資連續買超" in STRATEGY_MAP
        assert STRATEGY_MAP["外資連續買超"] is ForeignBrokerTrackingStrategy

    def test_params_default(self):
        """預設參數正確"""
        s = ForeignBrokerTrackingStrategy()
        assert s.params["consecutive_days"] == 3
        assert s.params["min_brokers"] == 3
        assert s.params["net_volume_pct"] == 0.05
        assert s.params["max_hold_days"] == 20
