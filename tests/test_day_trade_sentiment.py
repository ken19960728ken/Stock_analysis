"""
當沖情緒反轉策略測試

覆蓋項目：
1. 正常信號產生（Z-Score 達閾值）
2. 無 day_trade 資料時 graceful return
3. 過濾條件（min/max ratio）
4. 參數邊界
5. 策略註冊驗證
"""

import numpy as np
import pandas as pd
import pytest

from analysis.strategies.day_trade_sentiment import DayTradeSentimentStrategy


@pytest.fixture
def base_ohlcv():
    """100 天 OHLCV 基礎資料"""
    np.random.seed(42)
    n = 100
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "date": dates,
        "stock_id": "2330",
        "open": close - 0.5,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": np.random.randint(10_000_000, 50_000_000, n),
    })


class TestDayTradeSentimentBasic:
    """基本功能測試"""

    def test_no_day_trade_data_graceful_return(self, base_ohlcv):
        """無當沖資料 → 靜默返回，不產生訊號"""
        s = DayTradeSentimentStrategy()
        result = s.generate_signals(base_ohlcv)
        assert "signal" in result.columns
        assert (result["signal"] == 0).all()

    def test_with_day_trade_ratio_column(self, base_ohlcv):
        """有 day_trade_ratio 欄位 → 正常運作"""
        df = base_ohlcv.copy()
        np.random.seed(123)
        df["day_trade_ratio"] = np.random.uniform(0.02, 0.15, len(df))
        s = DayTradeSentimentStrategy()
        result = s.generate_signals(df)
        assert "signal" in result.columns
        assert set(result["signal"].unique()).issubset({-1, 0, 1})

    def test_with_day_trade_volume_column(self, base_ohlcv):
        """有 day_trade_volume + volume → 自動計算 ratio"""
        df = base_ohlcv.copy()
        df["day_trade_volume"] = df["volume"] * 0.05
        s = DayTradeSentimentStrategy()
        result = s.generate_signals(df)
        assert "signal" in result.columns


class TestDayTradeSentimentSignals:
    """訊號產生測試"""

    def test_oversold_buy_signal(self, base_ohlcv):
        """Z-Score 極低 → 買入訊號"""
        df = base_ohlcv.copy()
        n = len(df)
        # 前 80 天正常當沖比例，後 20 天驟降（散戶離場）
        ratio = np.full(n, 0.10)
        ratio[-20:] = 0.02  # 驟降
        df["day_trade_ratio"] = ratio
        s = DayTradeSentimentStrategy()
        s.set_params(zscore_window=60, oversold_z=-1.0)
        result = s.generate_signals(df)
        # 後段應有買入訊號
        assert (result["signal"] == 1).any()

    def test_overbought_sell_signal(self, base_ohlcv):
        """Z-Score 極高 → 賣出訊號"""
        df = base_ohlcv.copy()
        n = len(df)
        # 前 80 天正常，後 20 天飆升（散戶瘋狂）
        ratio = np.full(n, 0.05)
        ratio[-20:] = 0.30  # 飆升
        df["day_trade_ratio"] = ratio
        s = DayTradeSentimentStrategy()
        s.set_params(zscore_window=60, overbought_z=1.5)
        result = s.generate_signals(df)
        assert (result["signal"] == -1).any()

    def test_stable_ratio_no_signal(self, base_ohlcv):
        """當沖比例穩定 → 不應有訊號"""
        df = base_ohlcv.copy()
        df["day_trade_ratio"] = 0.08  # 穩定不變
        s = DayTradeSentimentStrategy()
        result = s.generate_signals(df)
        # Z-Score 應接近 0（std 接近 0），不應觸發
        buy_count = (result["signal"] == 1).sum()
        sell_count = (result["signal"] == -1).sum()
        assert buy_count == 0
        assert sell_count == 0


class TestDayTradeSentimentFilter:
    """過濾條件測試"""

    def test_below_min_ratio_filtered(self, base_ohlcv):
        """當沖比例低於 min → 不產生訊號"""
        df = base_ohlcv.copy()
        # 全部低於 min_day_trade_ratio
        df["day_trade_ratio"] = 0.005
        s = DayTradeSentimentStrategy()
        s.set_params(min_day_trade_ratio=0.01)
        result = s.generate_signals(df)
        assert (result["signal"] == 0).all()

    def test_above_max_ratio_filtered(self, base_ohlcv):
        """當沖比例高於 max → 不產生訊號"""
        df = base_ohlcv.copy()
        df["day_trade_ratio"] = 0.60
        s = DayTradeSentimentStrategy()
        s.set_params(max_day_trade_ratio=0.50)
        result = s.generate_signals(df)
        assert (result["signal"] == 0).all()

    def test_zero_volume_handled(self, base_ohlcv):
        """volume = 0 → 不崩潰"""
        df = base_ohlcv.copy()
        df["day_trade_volume"] = 1000
        df["volume"] = 0
        s = DayTradeSentimentStrategy()
        result = s.generate_signals(df)
        assert "signal" in result.columns


class TestDayTradeSentimentParams:
    """參數邊界測試"""

    def test_set_params(self):
        """set_params 正確更新"""
        s = DayTradeSentimentStrategy()
        s.set_params(zscore_window=30, overbought_z=3.0)
        assert s.params["zscore_window"] == 30
        assert s.params["overbought_z"] == 3.0

    def test_get_params(self):
        """get_params 返回副本"""
        s = DayTradeSentimentStrategy()
        p = s.get_params()
        p["zscore_window"] = 999
        assert s.params["zscore_window"] != 999

    def test_strategy_name(self):
        s = DayTradeSentimentStrategy()
        assert s.name == "當沖情緒反轉"

    def test_strategy_registered(self):
        """策略已註冊到 STRATEGY_MAP"""
        from analysis.strategies import STRATEGY_MAP
        assert "當沖情緒反轉" in STRATEGY_MAP
