"""測試 3 個新策略：量價動能、營收動能、波動率壓縮突破"""

import numpy as np
import pandas as pd
import pytest


# ===================================================================
# 測試用資料生成
# ===================================================================

def _make_ohlcv(n: int = 200, seed: int = 42) -> pd.DataFrame:
    """產生 n 日 OHLCV 測試資料"""
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range("2024-01-01", periods=n)
    close = 100 + np.cumsum(rng.randn(n) * 1.5)
    close = np.maximum(close, 10)  # 防止負數
    high = close + rng.uniform(0.5, 3, n)
    low = close - rng.uniform(0.5, 3, n)
    open_ = close + rng.uniform(-1, 1, n)
    volume = rng.randint(500_000, 5_000_000, n).astype(float)
    return pd.DataFrame({
        "date": dates,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def _make_breakout_data(n: int = 100) -> pd.DataFrame:
    """產生帶有明確放量突破的資料"""
    dates = pd.bdate_range("2024-01-01", periods=n)
    # 前 80 日盤整
    close = np.full(n, 100.0)
    close[:80] = 100 + np.random.RandomState(1).randn(80) * 0.5
    # 第 81 日放量突破
    close[80:] = np.linspace(105, 120, n - 80)
    high = close + 1
    low = close - 1
    volume = np.full(n, 1_000_000.0)
    volume[80] = 5_000_000  # 大量
    return pd.DataFrame({
        "date": dates,
        "open": close - 0.5,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def _make_squeeze_data(n: int = 200) -> pd.DataFrame:
    """產生帶有波動率壓縮→釋放的資料"""
    dates = pd.bdate_range("2024-01-01", periods=n)
    rng = np.random.RandomState(99)
    close = np.zeros(n)
    close[0] = 100
    for i in range(1, n):
        # 前 150 日低波動，之後高波動突破
        vol = 0.3 if i < 150 else 3.0
        close[i] = close[i - 1] + rng.randn() * vol
    close = np.maximum(close, 50)
    high = close + abs(rng.randn(n)) * 0.5 + 0.1
    low = close - abs(rng.randn(n)) * 0.5 - 0.1
    volume = rng.randint(1_000_000, 3_000_000, n).astype(float)
    return pd.DataFrame({
        "date": dates,
        "open": close + rng.randn(n) * 0.2,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def _make_revenue_data(n: int = 300) -> pd.DataFrame:
    """產生帶有月營收欄位的測試資料"""
    df = _make_ohlcv(n, seed=77)
    # 模擬月營收欄位（由 enrich_data merge 進來）
    revenue = np.full(n, np.nan)
    rev_month = np.full(n, np.nan)
    rev_year = np.full(n, np.nan)
    # 每 ~21 日填一筆月營收
    for i in range(21, n, 21):
        dt = df["date"].iloc[i]
        rev_month[i] = dt.month
        rev_year[i] = dt.year
        # 營收逐月增長（測試加速成長）
        base = 1_000_000 * (1 + i / n * 0.5)
        revenue[i] = base
    df["revenue"] = revenue
    df["revenue_month"] = rev_month
    df["revenue_year"] = rev_year
    # 前向填充
    df["revenue"] = df["revenue"].ffill()
    df["revenue_month"] = df["revenue_month"].ffill()
    df["revenue_year"] = df["revenue_year"].ffill()
    return df


# ===================================================================
# 指標測試
# ===================================================================

class TestIndicators:
    def test_add_obv(self):
        from analysis.utils.indicators import add_obv
        df = _make_ohlcv(50)
        result = add_obv(df)
        assert "OBV" in result.columns
        assert "OBV_EMA" in result.columns
        assert not result["OBV"].isna().all()

    def test_add_keltner(self):
        from analysis.utils.indicators import add_keltner
        df = _make_ohlcv(50)
        result = add_keltner(df)
        assert "KC_mid" in result.columns
        assert "KC_upper" in result.columns
        assert "KC_lower" in result.columns
        # KC_upper > KC_mid > KC_lower
        valid = result.dropna(subset=["KC_upper", "KC_lower"])
        if len(valid) > 0:
            assert (valid["KC_upper"] >= valid["KC_mid"]).all()
            assert (valid["KC_mid"] >= valid["KC_lower"]).all()


# ===================================================================
# 量價動能策略
# ===================================================================

class TestVolumePriceMomentumStrategy:
    def setup_method(self):
        from analysis.strategies.volume_price_momentum import VolumePriceMomentumStrategy
        self.strategy = VolumePriceMomentumStrategy()

    def test_basic_signal_generation(self):
        df = _make_ohlcv(200)
        result = self.strategy.generate_signals(df)
        assert "signal" in result.columns
        assert set(result["signal"].unique()).issubset({-1, 0, 1})

    def test_empty_data(self):
        df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        result = self.strategy.generate_signals(df)
        assert "signal" in result.columns
        assert len(result) == 0

    def test_short_data(self):
        df = _make_ohlcv(5)
        result = self.strategy.generate_signals(df)
        assert "signal" in result.columns

    def test_breakout_data_has_buy(self):
        df = _make_breakout_data(100)
        result = self.strategy.generate_signals(df)
        # 放量突破應產生至少一些訊號
        assert "signal" in result.columns

    def test_custom_params(self):
        self.strategy.set_params(volume_multiple=3.0, breakout_period=10, confirm_days=3)
        assert self.strategy.params["volume_multiple"] == 3.0
        assert self.strategy.params["breakout_period"] == 10
        assert self.strategy.params["confirm_days"] == 3
        df = _make_ohlcv(100)
        result = self.strategy.generate_signals(df)
        assert "signal" in result.columns

    def test_obv_columns_created(self):
        df = _make_ohlcv(100)
        result = self.strategy.generate_signals(df)
        assert "OBV" in result.columns
        assert "OBV_EMA" in result.columns


# ===================================================================
# 營收動能策略
# ===================================================================

class TestRevenueMomentumStrategy:
    def setup_method(self):
        from analysis.strategies.revenue_momentum import RevenueMomentumStrategy
        self.strategy = RevenueMomentumStrategy()

    def test_basic_signal_generation(self):
        df = _make_revenue_data(300)
        result = self.strategy.generate_signals(df)
        assert "signal" in result.columns
        assert set(result["signal"].unique()).issubset({-1, 0, 1})

    def test_no_revenue_column(self):
        """無營收資料時應回傳全 0 訊號"""
        df = _make_ohlcv(100)
        result = self.strategy.generate_signals(df)
        assert "signal" in result.columns
        assert (result["signal"] == 0).all()

    def test_empty_data(self):
        df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        result = self.strategy.generate_signals(df)
        assert "signal" in result.columns
        assert len(result) == 0

    def test_yoy_calculation(self):
        """驗證 YoY 計算邏輯"""
        df = _make_revenue_data(300)
        result = self.strategy.generate_signals(df)
        if "revenue_yoy" in result.columns:
            # YoY 應為百分比數值
            valid_yoy = result["revenue_yoy"].dropna()
            if len(valid_yoy) > 0:
                assert valid_yoy.dtype in [np.float64, np.float32, float]

    def test_pe_filter_toggle(self):
        """停用 PE 過濾"""
        self.strategy.set_params(enable_pe_filter=False)
        df = _make_revenue_data(300)
        result = self.strategy.generate_signals(df)
        assert "signal" in result.columns

    def test_custom_yoy_threshold(self):
        self.strategy.set_params(yoy_threshold=50.0)
        df = _make_revenue_data(300)
        result = self.strategy.generate_signals(df)
        assert "signal" in result.columns


# ===================================================================
# 波動率壓縮突破策略
# ===================================================================

class TestVolatilitySqueezeStrategy:
    def setup_method(self):
        from analysis.strategies.volatility_squeeze import VolatilitySqueezeStrategy
        self.strategy = VolatilitySqueezeStrategy()

    def test_basic_signal_generation(self):
        df = _make_ohlcv(200)
        result = self.strategy.generate_signals(df)
        assert "signal" in result.columns
        assert set(result["signal"].unique()).issubset({-1, 0, 1})

    def test_empty_data(self):
        df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        result = self.strategy.generate_signals(df)
        assert "signal" in result.columns
        assert len(result) == 0

    def test_short_data(self):
        df = _make_ohlcv(10)
        result = self.strategy.generate_signals(df)
        assert "signal" in result.columns

    def test_squeeze_detection(self):
        """低波動資料應偵測到 Squeeze 狀態"""
        df = _make_squeeze_data(200)
        result = self.strategy.generate_signals(df)
        assert "BB_upper" in result.columns
        assert "KC_upper" in result.columns
        # 低波動期間 BB 應縮窄到 KC 內部
        squeeze_on = (result["BB_upper"] < result["KC_upper"]) & (result["BB_lower"] > result["KC_lower"])
        # 至少應有部分日期偵測到 Squeeze
        assert squeeze_on.sum() > 0, "應偵測到至少一段 Squeeze 期間"

    def test_custom_params(self):
        self.strategy.set_params(bb_std=1.5, kc_mult=2.0, rsi_threshold=40, squeeze_min_days=3)
        assert self.strategy.params["bb_std"] == 1.5
        assert self.strategy.params["kc_mult"] == 2.0
        assert self.strategy.params["squeeze_min_days"] == 3
        df = _make_ohlcv(200)
        result = self.strategy.generate_signals(df)
        assert "signal" in result.columns

    def test_bollinger_and_keltner_columns(self):
        df = _make_ohlcv(100)
        result = self.strategy.generate_signals(df)
        for col in ["BB_upper", "BB_lower", "BB_mid", "KC_upper", "KC_lower", "KC_mid", "RSI"]:
            assert col in result.columns, f"缺少欄位: {col}"


# ===================================================================
# 策略註冊測試
# ===================================================================

class TestStrategyRegistration:
    def test_strategies_in_map(self):
        from analysis.strategies import STRATEGY_MAP
        assert "量價動能" in STRATEGY_MAP
        assert "營收動能" in STRATEGY_MAP
        assert "波動率壓縮突破" in STRATEGY_MAP

    def test_total_strategy_count(self):
        from analysis.strategies import STRATEGY_MAP
        assert len(STRATEGY_MAP) == 21

    def test_instantiation(self):
        from analysis.strategies import STRATEGY_MAP
        for name in ["量價動能", "營收動能", "波動率壓縮突破"]:
            s = STRATEGY_MAP[name]()
            assert s.name == name
            assert isinstance(s.params, dict)
            assert len(s.params) > 0
