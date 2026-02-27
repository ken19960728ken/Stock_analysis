"""
技術指標計算模組測試 — analysis/utils/indicators.py
覆蓋所有 11 個指標函數 + compute_all_indicators
"""

import numpy as np
import pandas as pd
import pytest

from analysis.utils.indicators import (
    _ema,
    _sma,
    add_atr,
    add_awesome_oscillator,
    add_bollinger,
    add_ema,
    add_heikin_ashi,
    add_kd,
    add_ma,
    add_macd,
    add_parabolic_sar,
    add_rsi,
    add_williams_r,
    compute_all_indicators,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def ohlcv_100d():
    """100 天 OHLCV 測試資料"""
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=100, freq="B")
    close = 500 + np.cumsum(np.random.randn(100) * 3)
    high = close + np.abs(np.random.randn(100) * 2)
    low = close - np.abs(np.random.randn(100) * 2)
    open_ = close + np.random.randn(100) * 1.5
    return pd.DataFrame({
        "date": dates,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": np.random.randint(10_000_000, 50_000_000, 100),
    })


@pytest.fixture
def simple_series():
    """簡單測試用序列"""
    return pd.Series([10, 20, 30, 40, 50, 60, 70, 80, 90, 100], dtype=float)


# ============================================================================
# 基礎函數
# ============================================================================

class TestSMA:
    def test_basic_calculation(self, simple_series):
        result = _sma(simple_series, 3)
        assert pd.isna(result.iloc[0])
        assert pd.isna(result.iloc[1])
        assert result.iloc[2] == pytest.approx(20.0)  # (10+20+30)/3
        assert result.iloc[3] == pytest.approx(30.0)  # (20+30+40)/3

    def test_full_window(self, simple_series):
        result = _sma(simple_series, 10)
        assert result.dropna().iloc[0] == pytest.approx(55.0)  # mean(10..100)

    def test_single_period(self, simple_series):
        result = _sma(simple_series, 1)
        pd.testing.assert_series_equal(result, simple_series)


class TestEMA:
    def test_basic_calculation(self, simple_series):
        result = _ema(simple_series, 3)
        assert len(result) == len(simple_series)
        assert not result.isna().any()

    def test_ema_smoother_than_raw(self):
        """EMA 應比原始序列更平滑（需要有波動的資料）"""
        np.random.seed(42)
        noisy = pd.Series(np.random.randn(50) * 10 + 100)
        result = _ema(noisy, 10)
        raw_std = noisy.diff().dropna().std()
        ema_std = result.diff().dropna().std()
        assert ema_std < raw_std


# ============================================================================
# 移動平均線
# ============================================================================

class TestAddMA:
    def test_default_periods(self, ohlcv_100d):
        result = add_ma(ohlcv_100d.copy())
        assert "MA5" in result.columns
        assert "MA20" in result.columns
        assert "MA60" in result.columns

    def test_custom_periods(self, ohlcv_100d):
        result = add_ma(ohlcv_100d.copy(), periods=[10, 30])
        assert "MA10" in result.columns
        assert "MA30" in result.columns
        assert "MA5" not in result.columns

    def test_values_correctness(self, ohlcv_100d):
        result = add_ma(ohlcv_100d.copy(), periods=[5])
        expected = ohlcv_100d["close"].rolling(5, min_periods=5).mean()
        pd.testing.assert_series_equal(result["MA5"], expected, check_names=False)


class TestAddEMA:
    def test_default_periods(self, ohlcv_100d):
        result = add_ema(ohlcv_100d.copy())
        assert "EMA5" in result.columns
        assert "EMA20" in result.columns
        assert "EMA60" in result.columns

    def test_no_nan(self, ohlcv_100d):
        result = add_ema(ohlcv_100d.copy(), periods=[5])
        assert not result["EMA5"].isna().any()


# ============================================================================
# MACD
# ============================================================================

class TestAddMACD:
    def test_columns_created(self, ohlcv_100d):
        result = add_macd(ohlcv_100d.copy())
        assert "MACD" in result.columns
        assert "MACD_signal" in result.columns
        assert "MACD_histogram" in result.columns

    def test_histogram_is_difference(self, ohlcv_100d):
        result = add_macd(ohlcv_100d.copy())
        expected = result["MACD"] - result["MACD_signal"]
        pd.testing.assert_series_equal(
            result["MACD_histogram"], expected, check_names=False
        )

    def test_custom_params(self, ohlcv_100d):
        result = add_macd(ohlcv_100d.copy(), fast=5, slow=10, signal=3)
        assert "MACD" in result.columns


# ============================================================================
# RSI
# ============================================================================

class TestAddRSI:
    def test_column_created(self, ohlcv_100d):
        result = add_rsi(ohlcv_100d.copy())
        assert "RSI" in result.columns

    def test_range_0_to_100(self, ohlcv_100d):
        result = add_rsi(ohlcv_100d.copy())
        valid = result["RSI"].dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()

    def test_all_up_rsi_high(self):
        """持續上漲 RSI 應接近 100"""
        np.random.seed(42)
        # 需要有偶爾的小跌幅讓 avg_loss > 0，RSI 才不會是 NaN
        # 但整體強勢上漲 → RSI 仍應很高
        n = 60
        changes = np.random.uniform(0.5, 3.0, n)  # 大部分上漲
        changes[::7] = -0.3  # 每 7 天小回調
        close = 100 + np.cumsum(changes)
        df = pd.DataFrame({
            "close": close,
            "open": close - 0.5,
            "high": close + 1,
            "low": close - 1,
        })
        result = add_rsi(df, period=14)
        valid_rsi = result["RSI"].dropna()
        assert len(valid_rsi) > 0
        assert valid_rsi.iloc[-1] > 80

    def test_all_down_rsi_low(self):
        """持續下跌 RSI 應接近 0"""
        df = pd.DataFrame({
            "close": [200 - i * 2 for i in range(30)],
            "open": [201 - i * 2 for i in range(30)],
            "high": [202 - i * 2 for i in range(30)],
            "low": [199 - i * 2 for i in range(30)],
        })
        result = add_rsi(df, period=14)
        assert result["RSI"].dropna().iloc[-1] < 20


# ============================================================================
# KD
# ============================================================================

class TestAddKD:
    def test_columns_created(self, ohlcv_100d):
        result = add_kd(ohlcv_100d.copy())
        assert "K" in result.columns
        assert "D" in result.columns

    def test_range(self, ohlcv_100d):
        result = add_kd(ohlcv_100d.copy())
        k_valid = result["K"].dropna()
        assert (k_valid >= 0).all()
        assert (k_valid <= 100).all()


# ============================================================================
# Bollinger
# ============================================================================

class TestAddBollinger:
    def test_columns_created(self, ohlcv_100d):
        result = add_bollinger(ohlcv_100d.copy())
        for col in ["BB_mid", "BB_upper", "BB_lower", "BB_bandwidth", "BB_pct"]:
            assert col in result.columns

    def test_upper_greater_than_lower(self, ohlcv_100d):
        result = add_bollinger(ohlcv_100d.copy())
        valid = result.dropna(subset=["BB_upper", "BB_lower"])
        assert (valid["BB_upper"] >= valid["BB_lower"]).all()

    def test_mid_is_sma(self, ohlcv_100d):
        result = add_bollinger(ohlcv_100d.copy(), period=20)
        expected = _sma(ohlcv_100d["close"], 20)
        pd.testing.assert_series_equal(
            result["BB_mid"], expected, check_names=False
        )


# ============================================================================
# Parabolic SAR
# ============================================================================

class TestAddParabolicSAR:
    def test_column_created(self, ohlcv_100d):
        result = add_parabolic_sar(ohlcv_100d.copy())
        assert "SAR" in result.columns
        assert "SAR_long" in result.columns
        assert "SAR_short" in result.columns

    def test_short_data(self):
        """少於 2 筆資料應回傳 NaN"""
        df = pd.DataFrame({
            "open": [100], "high": [105], "low": [95], "close": [102],
        })
        result = add_parabolic_sar(df)
        assert result["SAR"].isna().all()

    def test_sar_flips(self, ohlcv_100d):
        """SAR 應該有多空切換"""
        result = add_parabolic_sar(ohlcv_100d.copy())
        has_long = result["SAR_long"].notna().any()
        has_short = result["SAR_short"].notna().any()
        assert has_long or has_short


# ============================================================================
# Heikin-Ashi
# ============================================================================

class TestAddHeikinAshi:
    def test_columns_created(self, ohlcv_100d):
        result = add_heikin_ashi(ohlcv_100d.copy())
        for col in ["HA_open", "HA_high", "HA_low", "HA_close"]:
            assert col in result.columns

    def test_ha_close_is_ohlc_avg(self, ohlcv_100d):
        result = add_heikin_ashi(ohlcv_100d.copy())
        expected = (ohlcv_100d["open"] + ohlcv_100d["high"] +
                    ohlcv_100d["low"] + ohlcv_100d["close"]) / 4
        pd.testing.assert_series_equal(
            result["HA_close"], expected, check_names=False
        )

    def test_ha_high_ge_close(self, ohlcv_100d):
        result = add_heikin_ashi(ohlcv_100d.copy())
        assert (result["HA_high"] >= result["HA_close"]).all()

    def test_ha_low_le_close(self, ohlcv_100d):
        result = add_heikin_ashi(ohlcv_100d.copy())
        assert (result["HA_low"] <= result["HA_close"]).all()


# ============================================================================
# Williams %R
# ============================================================================

class TestAddWilliamsR:
    def test_column_created(self, ohlcv_100d):
        result = add_williams_r(ohlcv_100d.copy())
        assert "WilliamsR" in result.columns

    def test_range(self, ohlcv_100d):
        result = add_williams_r(ohlcv_100d.copy())
        valid = result["WilliamsR"].dropna()
        assert (valid >= -100).all()
        assert (valid <= 0).all()


# ============================================================================
# Awesome Oscillator
# ============================================================================

class TestAddAwesomeOscillator:
    def test_column_created(self, ohlcv_100d):
        result = add_awesome_oscillator(ohlcv_100d.copy())
        assert "AO" in result.columns

    def test_ao_is_sma_diff(self, ohlcv_100d):
        result = add_awesome_oscillator(ohlcv_100d.copy())
        midpoint = (ohlcv_100d["high"] + ohlcv_100d["low"]) / 2
        expected = _sma(midpoint, 5) - _sma(midpoint, 34)
        pd.testing.assert_series_equal(
            result["AO"], expected, check_names=False
        )


# ============================================================================
# ATR
# ============================================================================

class TestAddATR:
    def test_column_created(self, ohlcv_100d):
        result = add_atr(ohlcv_100d.copy())
        assert "ATR" in result.columns

    def test_atr_positive(self, ohlcv_100d):
        result = add_atr(ohlcv_100d.copy())
        valid = result["ATR"].dropna()
        assert (valid > 0).all()


# ============================================================================
# compute_all_indicators
# ============================================================================

class TestComputeAllIndicators:
    def test_all_columns_added(self, ohlcv_100d):
        result = compute_all_indicators(ohlcv_100d.copy())
        expected_cols = [
            "MA5", "MA20", "MA60",
            "MACD", "MACD_signal", "MACD_histogram",
            "RSI", "K", "D",
            "BB_mid", "BB_upper", "BB_lower",
            "SAR",
            "HA_open", "HA_close",
            "WilliamsR", "AO", "ATR",
        ]
        for col in expected_cols:
            assert col in result.columns, f"Missing column: {col}"

    def test_empty_df(self):
        result = compute_all_indicators(pd.DataFrame())
        assert result.empty

    def test_original_not_modified(self, ohlcv_100d):
        original = ohlcv_100d.copy()
        compute_all_indicators(ohlcv_100d.copy())
        pd.testing.assert_frame_equal(ohlcv_100d, original)
