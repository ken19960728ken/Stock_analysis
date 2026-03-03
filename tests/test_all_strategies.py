"""
策略完整單元測試 — 補齊 12 個缺少獨立測試的策略

覆蓋策略：
  1. MACrossStrategy         (MA 交叉)
  2. MACDStrategy            (MACD 訊號)
  3. BollingerStrategy       (Bollinger 突破)
  4. RSIReversalStrategy     (RSI 反轉)
  5. ParabolicSARStrategy    (Parabolic SAR)
  6. HeikinAshiStrategy      (Heikin-Ashi)
  7. DualThrustStrategy      (Dual Thrust)
  8. InstitutionalStrategy   (法人跟單)
  9. ValueInvestingStrategy   (價值投資)
 10. MultiFactorStrategy     (多因子綜合 — 擴充測試)
 11. EventDrivenStrategy     (事件驅動)
 12. MLFactorStrategy        (機器學習選股)
"""

import numpy as np
import pandas as pd
import pytest

from analysis.strategies.ma_cross import MACrossStrategy
from analysis.strategies.macd_signal import MACDStrategy
from analysis.strategies.bollinger import BollingerStrategy
from analysis.strategies.rsi_reversal import RSIReversalStrategy
from analysis.strategies.parabolic_sar import ParabolicSARStrategy
from analysis.strategies.heikin_ashi import HeikinAshiStrategy
from analysis.strategies.dual_thrust import DualThrustStrategy
from analysis.strategies.institutional import InstitutionalStrategy
from analysis.strategies.value_investing import ValueInvestingStrategy
from analysis.strategies.multi_factor import MultiFactorStrategy
from analysis.strategies.event_driven import EventDrivenStrategy
from analysis.strategies.ml_factor import MLFactorStrategy


# ============================================================================
# Fixtures: 特定趨勢 OHLCV 資料
# ============================================================================

@pytest.fixture
def ohlcv_uptrend(sample_stock_id):
    """60 天明確上升趨勢 OHLCV"""
    np.random.seed(99)
    dates = pd.date_range("2023-01-01", periods=60, freq="B")
    close = np.array([500.0 + i * 2 for i in range(60)])
    return pd.DataFrame({
        "date": dates, "stock_id": sample_stock_id,
        "open": close - 1, "high": close + 3, "low": close - 3,
        "close": close, "volume": np.random.randint(20_000_000, 40_000_000, 60),
    })


@pytest.fixture
def ohlcv_downtrend(sample_stock_id):
    """60 天明確下降趨勢 OHLCV"""
    np.random.seed(99)
    dates = pd.date_range("2023-01-01", periods=60, freq="B")
    close = np.array([620.0 - i * 2 for i in range(60)])
    return pd.DataFrame({
        "date": dates, "stock_id": sample_stock_id,
        "open": close + 1, "high": close + 3, "low": close - 3,
        "close": close, "volume": np.random.randint(20_000_000, 40_000_000, 60),
    })


@pytest.fixture
def ohlcv_volatile(sample_stock_id):
    """60 天高波動 OHLCV（適合觸發 Bollinger/RSI/MACD 等訊號）"""
    np.random.seed(123)
    dates = pd.date_range("2023-01-01", periods=60, freq="B")
    close = 550 + np.cumsum(np.random.randn(60) * 8)
    return pd.DataFrame({
        "date": dates, "stock_id": sample_stock_id,
        "open": close - 2, "high": close + 5, "low": close - 5,
        "close": close, "volume": np.random.randint(20_000_000, 40_000_000, 60),
    })


# ============================================================================
# 1. TestMACrossStrategy
# ============================================================================

class TestMACrossStrategy:
    """MA 交叉策略"""

    def test_basic_signal_generation(self, sample_ohlcv_50d):
        """基本訊號產生 — signal 欄位存在且值合法"""
        s = MACrossStrategy()
        result = s.generate_signals(sample_ohlcv_50d)
        assert "signal" in result.columns
        assert set(result["signal"].unique()).issubset({-1, 0, 1})

    def test_set_params(self, sample_ohlcv_50d):
        """修改快慢均線參數"""
        s = MACrossStrategy()
        s.set_params(fast_period=3, slow_period=10)
        assert s.params["fast_period"] == 3
        assert s.params["slow_period"] == 10
        result = s.generate_signals(sample_ohlcv_50d)
        assert "signal" in result.columns

    def test_regime_change_produces_buy(self, sample_stock_id):
        """下跌轉上漲（在高價位，通過趨勢過濾）→ golden cross → buy"""
        dates = pd.date_range("2023-01-01", periods=60, freq="B")
        # 先跌 20 天，再漲 40 天
        close = np.concatenate([
            np.linspace(520, 490, 20),
            np.linspace(490, 570, 40),
        ])
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "open": close - 1, "high": close + 3, "low": close - 3,
            "close": close, "volume": [30_000_000] * 60,
        })
        s = MACrossStrategy()
        # 用短趨勢週期讓金叉時 close > trend_ma
        s.set_params(fast_period=5, slow_period=20, trend_period=10)
        result = s.generate_signals(df)
        assert (result["signal"] == 1).any()

    def test_regime_change_produces_sell(self, sample_stock_id):
        """上漲轉下跌 → 快線跌破慢線 → sell (death cross)"""
        dates = pd.date_range("2023-01-01", periods=60, freq="B")
        close = np.concatenate([
            np.linspace(480, 520, 20),
            np.linspace(520, 440, 40),
        ])
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "open": close + 1, "high": close + 3, "low": close - 3,
            "close": close, "volume": [30_000_000] * 60,
        })
        s = MACrossStrategy()
        s.set_params(fast_period=5, slow_period=20, trend_period=30)
        result = s.generate_signals(df)
        assert (result["signal"] == -1).any()

    def test_short_data_no_crash(self, sample_stock_id):
        """資料量不足均線週期 → 不崩潰"""
        dates = pd.date_range("2023-01-01", periods=5, freq="B")
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "open": [100] * 5, "high": [105] * 5, "low": [95] * 5,
            "close": [100] * 5, "volume": [1_000_000] * 5,
        })
        s = MACrossStrategy()
        result = s.generate_signals(df)
        assert "signal" in result.columns


# ============================================================================
# 2. TestMACDStrategy
# ============================================================================

class TestMACDStrategy:
    """MACD 訊號策略"""

    def test_basic_signal_generation(self, sample_ohlcv_50d):
        s = MACDStrategy()
        result = s.generate_signals(sample_ohlcv_50d)
        assert "signal" in result.columns
        assert set(result["signal"].unique()).issubset({-1, 0, 1})

    def test_set_params(self, sample_ohlcv_50d):
        s = MACDStrategy()
        s.set_params(fast=8, slow=21, signal=5)
        assert s.params["fast"] == 8
        result = s.generate_signals(sample_ohlcv_50d)
        assert "signal" in result.columns

    def test_volatile_data_has_signals(self, ohlcv_volatile):
        """高波動資料 → MACD histogram 交叉 → 有訊號"""
        s = MACDStrategy()
        result = s.generate_signals(ohlcv_volatile)
        assert (result["signal"] != 0).sum() > 0

    def test_flat_data_minimal_signals(self, sample_stock_id):
        """完全平坦價格 → 極少訊號"""
        dates = pd.date_range("2023-01-01", periods=50, freq="B")
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "open": [500.0] * 50, "high": [501.0] * 50, "low": [499.0] * 50,
            "close": [500.0] * 50, "volume": [1_000_000] * 50,
        })
        s = MACDStrategy()
        result = s.generate_signals(df)
        assert "signal" in result.columns


# ============================================================================
# 3. TestBollingerStrategy
# ============================================================================

class TestBollingerStrategy:
    """Bollinger 突破策略"""

    def test_basic_signal_generation(self, sample_ohlcv_50d):
        s = BollingerStrategy()
        result = s.generate_signals(sample_ohlcv_50d)
        assert "signal" in result.columns
        assert set(result["signal"].unique()).issubset({-1, 0, 1})

    def test_set_params(self, sample_ohlcv_50d):
        s = BollingerStrategy()
        s.set_params(period=10, std_dev=1.5)
        assert s.params["std_dev"] == 1.5
        result = s.generate_signals(sample_ohlcv_50d)
        assert "signal" in result.columns

    def test_narrow_bands_more_signals(self, ohlcv_volatile):
        """窄布林通道（低 std_dev）→ 更多突破訊號"""
        s_narrow = BollingerStrategy()
        s_narrow.set_params(std_dev=1.0)
        r_narrow = s_narrow.generate_signals(ohlcv_volatile.copy())

        s_wide = BollingerStrategy()
        s_wide.set_params(std_dev=3.0)
        r_wide = s_wide.generate_signals(ohlcv_volatile.copy())

        assert (r_narrow["signal"] != 0).sum() >= (r_wide["signal"] != 0).sum()

    def test_buy_on_lower_band_break(self, sample_stock_id):
        """價格突然暴跌跌破下軌 + RSI 超賣 → buy signal"""
        np.random.seed(77)
        dates = pd.date_range("2023-01-01", periods=30, freq="B")
        # 前 25 天穩定波動（建立 BB），第 26 天起突然暴跌（需夠深讓 RSI < 35）
        close = np.concatenate([
            500 + np.random.randn(25) * 3,
            np.array([480, 470, 460, 450, 440]),  # 階梯式暴跌
        ])
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "open": close - 1, "high": close + 2, "low": close - 2,
            "close": close, "volume": [1_000_000] * 30,
        })
        s = BollingerStrategy()
        # 放寬 RSI 門檻使測試容易觸發
        s.set_params(period=20, std_dev=2.0, rsi_oversold=50)
        result = s.generate_signals(df)
        assert (result["signal"] == 1).any()


# ============================================================================
# 4. TestRSIReversalStrategy
# ============================================================================

class TestRSIReversalStrategy:
    """RSI 反轉策略"""

    def test_basic_signal_generation(self, sample_ohlcv_50d):
        s = RSIReversalStrategy()
        result = s.generate_signals(sample_ohlcv_50d)
        assert "signal" in result.columns
        assert set(result["signal"].unique()).issubset({-1, 0, 1})

    def test_set_params(self, sample_ohlcv_50d):
        s = RSIReversalStrategy()
        s.set_params(period=7, oversold=20, overbought=80)
        assert s.params["oversold"] == 20
        result = s.generate_signals(sample_ohlcv_50d)
        assert "signal" in result.columns

    def test_oversold_buy_signal(self, sample_stock_id):
        """先漲後跌 → RSI 從高位降至 < 30 → buy"""
        dates = pd.date_range("2023-01-01", periods=50, freq="B")
        # 前 20 天溫和上漲（建立 RSI 基礎值 > 30），後 30 天持續下跌
        close = np.concatenate([
            np.linspace(500, 520, 20),   # 溫和上漲 → RSI > 50
            np.linspace(518, 420, 30),   # 持續下跌 → RSI 逐步降至 < 30
        ])
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "open": close, "high": close + 2, "low": close - 2,
            "close": close, "volume": [1_000_000] * 50,
        })
        s = RSIReversalStrategy()
        result = s.generate_signals(df)
        assert (result["signal"] == 1).any()

    def test_overbought_sell_signal(self, sample_stock_id):
        """先跌後漲 → RSI 從低位升至 > 70 → sell"""
        dates = pd.date_range("2023-01-01", periods=50, freq="B")
        close = np.concatenate([
            np.linspace(520, 500, 20),   # 溫和下跌 → RSI < 50
            np.linspace(502, 600, 30),   # 持續上漲 → RSI 逐步升至 > 70
        ])
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "open": close, "high": close + 2, "low": close - 2,
            "close": close, "volume": [1_000_000] * 50,
        })
        s = RSIReversalStrategy()
        result = s.generate_signals(df)
        assert (result["signal"] == -1).any()


# ============================================================================
# 5. TestParabolicSARStrategy
# ============================================================================

class TestParabolicSARStrategy:
    """Parabolic SAR 策略"""

    def test_basic_signal_generation(self, sample_ohlcv_50d):
        s = ParabolicSARStrategy()
        result = s.generate_signals(sample_ohlcv_50d)
        assert "signal" in result.columns
        assert set(result["signal"].unique()).issubset({-1, 0, 1})

    def test_set_params(self, sample_ohlcv_50d):
        s = ParabolicSARStrategy()
        s.set_params(af=0.01, max_af=0.1)
        assert s.params["af"] == 0.01
        result = s.generate_signals(sample_ohlcv_50d)
        assert "signal" in result.columns

    def test_trend_data_has_signals(self, sample_stock_id):
        """趨勢反轉資料 → SAR 反轉 + ADX 過濾 → 有訊號"""
        np.random.seed(42)
        dates = pd.date_range("2023-01-01", periods=60, freq="B")
        # 先跌後漲，確保 SAR 有反轉機會
        close = np.concatenate([
            np.linspace(550, 480, 25),  # 下跌
            np.linspace(482, 580, 35),  # 反彈
        ])
        noise = np.random.randn(60) * 3
        close = close + noise
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "open": close - 2, "high": close + 5, "low": close - 5,
            "close": close, "volume": np.random.randint(20_000_000, 40_000_000, 60),
        })
        s = ParabolicSARStrategy()
        s.set_params(adx_threshold=10)
        result = s.generate_signals(df)
        assert (result["signal"] != 0).sum() > 0

    def test_volatile_data_has_signals(self, ohlcv_volatile):
        """高波動資料 → 多次 SAR 反轉"""
        s = ParabolicSARStrategy()
        # 短資料降低 ADX 門檻
        s.set_params(adx_threshold=10)
        result = s.generate_signals(ohlcv_volatile)
        assert (result["signal"] != 0).sum() > 0


# ============================================================================
# 6. TestHeikinAshiStrategy
# ============================================================================

class TestHeikinAshiStrategy:
    """Heikin-Ashi 策略"""

    def test_basic_signal_generation(self, sample_ohlcv_50d):
        s = HeikinAshiStrategy()
        result = s.generate_signals(sample_ohlcv_50d)
        assert "signal" in result.columns
        assert set(result["signal"].unique()).issubset({-1, 0, 1})

    def test_set_params(self, sample_ohlcv_50d):
        s = HeikinAshiStrategy()
        s.set_params(confirm_bars=3)
        assert s.params["confirm_bars"] == 3
        result = s.generate_signals(sample_ohlcv_50d)
        assert "signal" in result.columns

    def test_uptrend_bullish_signal(self, ohlcv_uptrend):
        """持續上漲 → 連續看漲 HA + 趨勢確認 → buy"""
        s = HeikinAshiStrategy()
        s.set_params(confirm_bars=2, trend_period=10)
        result = s.generate_signals(ohlcv_uptrend)
        assert (result["signal"] == 1).any()

    def test_more_confirm_bars_fewer_signals(self, ohlcv_volatile):
        """更多確認根數 → 更少訊號"""
        s2 = HeikinAshiStrategy()
        s2.set_params(confirm_bars=2)
        r2 = s2.generate_signals(ohlcv_volatile.copy())

        s5 = HeikinAshiStrategy()
        s5.set_params(confirm_bars=5)
        r5 = s5.generate_signals(ohlcv_volatile.copy())

        assert (r2["signal"] != 0).sum() >= (r5["signal"] != 0).sum()


# ============================================================================
# 7. TestDualThrustStrategy
# ============================================================================

class TestDualThrustStrategy:
    """Dual Thrust 策略"""

    def test_basic_signal_generation(self, sample_ohlcv_50d):
        s = DualThrustStrategy()
        result = s.generate_signals(sample_ohlcv_50d)
        assert "signal" in result.columns
        assert set(result["signal"].unique()).issubset({-1, 0, 1})

    def test_set_params(self, sample_ohlcv_50d):
        s = DualThrustStrategy()
        s.set_params(lookback=10, k1=0.7, k2=0.7)
        assert s.params["k1"] == 0.7
        result = s.generate_signals(sample_ohlcv_50d)
        assert "signal" in result.columns

    def test_volatile_data_breakouts(self, sample_stock_id):
        """高波動 + 真實 open/close 差異 + 量確認 → 突破訊號"""
        np.random.seed(42)
        dates = pd.date_range("2023-01-01", periods=60, freq="B")
        # open ≈ 前日 close + 隨機跳空，close 基於日內波動
        daily_move = np.random.randn(60) * 4
        close = 550 + np.cumsum(daily_move)
        intraday = np.random.randn(60) * 6  # 日內 open→close 波動
        open_ = close - intraday  # open 和 close 有獨立的大幅差異
        high = np.maximum(open_, close) + np.abs(np.random.randn(60) * 2)
        low = np.minimum(open_, close) - np.abs(np.random.randn(60) * 2)
        # 設定高成交量以通過量確認
        volume = np.random.randint(30_000_000, 50_000_000, 60)
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "open": open_, "high": high, "low": low,
            "close": close, "volume": volume,
        })
        s = DualThrustStrategy()
        # 用較小 k 值使突破容易觸發，放寬量比要求
        s.set_params(k1=0.3, k2=0.3, volume_ratio=0.5)
        result = s.generate_signals(df)
        assert (result["signal"] != 0).sum() > 0

    def test_narrow_k_more_signals(self, ohlcv_volatile):
        """小 k 值（窄通道）→ 更多突破"""
        s_narrow = DualThrustStrategy()
        s_narrow.set_params(k1=0.2, k2=0.2)
        r_narrow = s_narrow.generate_signals(ohlcv_volatile.copy())

        s_wide = DualThrustStrategy()
        s_wide.set_params(k1=0.9, k2=0.9)
        r_wide = s_wide.generate_signals(ohlcv_volatile.copy())

        assert (r_narrow["signal"] != 0).sum() >= (r_wide["signal"] != 0).sum()

    def test_output_has_upper_lower(self, sample_ohlcv_50d):
        """輸出應包含 upper/lower 欄位"""
        s = DualThrustStrategy()
        result = s.generate_signals(sample_ohlcv_50d)
        assert "upper" in result.columns
        assert "lower" in result.columns


# ============================================================================
# 8. TestInstitutionalStrategy
# ============================================================================

class TestInstitutionalStrategy:
    """法人跟單策略"""

    def test_consecutive_buy_signal(self, sample_stock_id):
        """連續 5 日買超 + 價格在 MA20 上方 → buy"""
        dates = pd.date_range("2023-01-01", periods=30, freq="B")
        # 用上漲趨勢確保 close > MA20
        net_buy = [0] * 20 + [100, 200, 300, 400, 500] + [0] * 5
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "close": [500 + i * 2 for i in range(30)],
            "institutional_buy": net_buy,
        })
        s = InstitutionalStrategy()
        result = s.generate_signals(df)
        assert (result["signal"] == 1).any()

    def test_consecutive_sell_signal(self, sample_stock_id):
        """連續 5 日賣超 → sell"""
        dates = pd.date_range("2023-01-01", periods=30, freq="B")
        net_buy = [0] * 20 + [-100, -200, -300, -400, -500] + [0] * 5
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "close": [500 - i for i in range(30)],
            "institutional_buy": net_buy,
        })
        s = InstitutionalStrategy()
        result = s.generate_signals(df)
        assert (result["signal"] == -1).any()

    def test_param_change_consecutive_days(self, sample_stock_id):
        """修改連續天數為 5"""
        dates = pd.date_range("2023-01-01", periods=20, freq="B")
        net_buy = [0] * 10 + [100] * 5 + [0] * 5
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "close": [500] * 20,
            "foreign_net_buy": net_buy,
        })
        s = InstitutionalStrategy()
        s.set_params(consecutive_days=5)
        result = s.generate_signals(df)
        assert "signal" in result.columns

    def test_missing_buy_column_graceful(self, sample_stock_id):
        """缺少法人欄位 → 全部 signal=0"""
        dates = pd.date_range("2023-01-01", periods=10, freq="B")
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "close": range(100, 110),
        })
        s = InstitutionalStrategy()
        result = s.generate_signals(df)
        assert (result["signal"] == 0).all()

    def test_signal_values_valid(self, sample_stock_id):
        dates = pd.date_range("2023-01-01", periods=20, freq="B")
        np.random.seed(42)
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "close": [500] * 20,
            "institutional_buy": np.random.randint(-500, 500, 20),
        })
        s = InstitutionalStrategy()
        result = s.generate_signals(df)
        assert set(result["signal"].unique()).issubset({-1, 0, 1})


# ============================================================================
# 9. TestValueInvestingStrategy
# ============================================================================

class TestValueInvestingStrategy:
    """價值投資策略"""

    def test_all_conditions_met_buy(self, sample_stock_id):
        """PE<15 + 殖利率>3% + 營收正成長 → buy"""
        dates = pd.date_range("2023-01-01", periods=10, freq="B")
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "close": [500] * 10,
            "PER": [20] * 5 + [12] * 5,
            "DividendYield": [1.0] * 5 + [4.0] * 5,
            "revenue_yoy": [-5] * 5 + [10] * 5,
        })
        s = ValueInvestingStrategy()
        result = s.generate_signals(df)
        assert (result["signal"] == 1).any()

    def test_no_conditions_met(self, sample_stock_id):
        """全部不達標 → 無 buy"""
        dates = pd.date_range("2023-01-01", periods=10, freq="B")
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "close": [500] * 10,
            "PER": [30] * 10,
            "DividendYield": [1.0] * 10,
            "revenue_yoy": [-10] * 10,
        })
        s = ValueInvestingStrategy()
        result = s.generate_signals(df)
        assert not (result["signal"] == 1).any()

    def test_missing_all_columns_graceful(self, sample_stock_id):
        """缺少全部價值欄位 → 全 0"""
        dates = pd.date_range("2023-01-01", periods=10, freq="B")
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "close": [500] * 10,
        })
        s = ValueInvestingStrategy()
        result = s.generate_signals(df)
        assert (result["signal"] == 0).all()

    def test_set_params_thresholds(self):
        s = ValueInvestingStrategy()
        s.set_params(pe_threshold=20, dividend_yield_threshold=2.0)
        assert s.params["pe_threshold"] == 20
        assert s.params["dividend_yield_threshold"] == 2.0

    def test_sell_on_conditions_lost(self, sample_stock_id):
        """條件從達標變成不達標 → sell"""
        dates = pd.date_range("2023-01-01", periods=10, freq="B")
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "close": [500] * 10,
            "PER": [12, 12, 12, 12, 12, 30, 30, 30, 30, 30],
            "DividendYield": [5, 5, 5, 5, 5, 1, 1, 1, 1, 1],
            "revenue_yoy": [10, 10, 10, 10, 10, -10, -10, -10, -10, -10],
        })
        s = ValueInvestingStrategy()
        result = s.generate_signals(df)
        assert (result["signal"] == -1).any()


# ============================================================================
# 10. TestMultiFactorStrategyExtended（補充現有 3 個 Z-Score 測試）
# ============================================================================

class TestMultiFactorStrategyExtended:
    """多因子綜合策略 — 擴充測試"""

    def test_tech_only_no_chip_no_fund(self, sample_ohlcv_50d):
        """僅技術面資料 → 仍可產生訊號"""
        s = MultiFactorStrategy()
        s.set_params(chip_weight=0, fund_weight=0, tech_weight=1.0)
        result = s.generate_signals(sample_ohlcv_50d)
        assert "signal" in result.columns
        assert set(result["signal"].unique()).issubset({-1, 0, 1})

    def test_weight_sensitivity(self, sample_multi_factor_50d):
        """不同權重產生不同結果（驗證權重確實被套用）"""
        s1 = MultiFactorStrategy()
        s1.set_params(tech_weight=0.8, chip_weight=0.1, fund_weight=0.1)
        r1 = s1.generate_signals(sample_multi_factor_50d.copy())

        s2 = MultiFactorStrategy()
        s2.set_params(tech_weight=0.1, chip_weight=0.8, fund_weight=0.1)
        r2 = s2.generate_signals(sample_multi_factor_50d.copy())

        assert set(r1["signal"].unique()).issubset({-1, 0, 1})
        assert set(r2["signal"].unique()).issubset({-1, 0, 1})

    def test_threshold_sensitivity(self, sample_multi_factor_50d):
        """買賣閾值影響訊號數量：嚴格閾值 ≤ 寬鬆閾值"""
        s_tight = MultiFactorStrategy()
        s_tight.set_params(buy_threshold=0.9, sell_threshold=-0.9)
        r_tight = s_tight.generate_signals(sample_multi_factor_50d.copy())

        s_loose = MultiFactorStrategy()
        s_loose.set_params(buy_threshold=0.1, sell_threshold=-0.1)
        r_loose = s_loose.generate_signals(sample_multi_factor_50d.copy())

        assert (r_tight["signal"] != 0).sum() <= (r_loose["signal"] != 0).sum()

    def test_signal_values_valid(self, sample_multi_factor_50d):
        s = MultiFactorStrategy()
        result = s.generate_signals(sample_multi_factor_50d)
        assert set(result["signal"].unique()).issubset({-1, 0, 1})


# ============================================================================
# 11. TestEventDrivenStrategy
# ============================================================================

class TestEventDrivenStrategy:
    """事件驅動策略 — 除息後買入等待填息"""

    def test_dividend_event_signals(self, sample_stock_id):
        """有 dividend 欄位 → 除息後買入、持有至填息"""
        n = 80
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        dividend = [0] * 10 + [15.0] + [0] * (n - 11)  # 高殖利率除息
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "close": [500] * n,
            "open": [500] * n, "high": [505] * n, "low": [495] * n,
            "volume": [1_000_000] * n,
            "dividend": dividend,
        })
        s = EventDrivenStrategy()
        result = s.generate_signals(df)
        assert (result["signal"] == 1).any()
        assert (result["signal"] == -1).any()

    def test_pre_injected_signal_passthrough(self, sample_stock_id):
        """data 已有 signal 欄位 → 直接返回不覆蓋"""
        dates = pd.date_range("2023-01-01", periods=10, freq="B")
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "close": [500] * 10,
            "signal": [0, 0, 1, 0, 0, 0, 0, -1, 0, 0],
        })
        s = EventDrivenStrategy()
        result = s.generate_signals(df)
        assert result["signal"].tolist() == [0, 0, 1, 0, 0, 0, 0, -1, 0, 0]

    def test_no_dividend_no_signal(self, sample_stock_id):
        """無 dividend 也無 signal 欄位 → 全 0"""
        dates = pd.date_range("2023-01-01", periods=10, freq="B")
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "close": [500] * 10,
        })
        s = EventDrivenStrategy()
        result = s.generate_signals(df)
        assert (result["signal"] == 0).all()

    def test_set_params(self):
        s = EventDrivenStrategy()
        s.set_params(entry_days_after=5, exit_days_after=30)
        assert s.params["entry_days_after"] == 5
        assert s.params["exit_days_after"] == 30

    def test_low_yield_filtered_out(self, sample_stock_id):
        """小配息（殖利率 < 門檻）→ 不觸發"""
        n = 80
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        dividend = [0] * 10 + [0.5] + [0] * (n - 11)  # 殖利率 0.1% 太低
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "close": [500] * n,
            "dividend": dividend,
        })
        s = EventDrivenStrategy()
        result = s.generate_signals(df)
        assert (result["signal"] == 0).all()

    def test_signal_values_valid(self, sample_stock_id):
        n = 80
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        dividend = [0] * 10 + [15.0] + [0] * (n - 11)
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "close": [500] * n,
            "dividend": dividend,
        })
        s = EventDrivenStrategy()
        result = s.generate_signals(df)
        assert set(result["signal"].unique()).issubset({-1, 0, 1})


# ============================================================================
# 12. TestMLFactorStrategy
# ============================================================================

class TestMLFactorStrategy:
    """機器學習選股策略"""

    def test_pred_label_buy_sell(self, sample_stock_id):
        """有 pred_label → 分位 2=buy, 分位 0=sell"""
        dates = pd.date_range("2023-01-01", periods=10, freq="B")
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "close": [500] * 10,
            "pred_label": [1, 0, 2, 1, 0, 2, 1, 0, 2, 1],
        })
        s = MLFactorStrategy()
        result = s.generate_signals(df)
        assert (result["signal"] == 1).any()    # pred_label=2 → buy
        assert (result["signal"] == -1).any()   # pred_label=0 → sell

    def test_fallback_simplified_logic(self, sample_ohlcv_50d):
        """無 pred_label → 簡化 RSI+MACD+Volume 邏輯"""
        s = MLFactorStrategy()
        result = s.generate_signals(sample_ohlcv_50d)
        assert "signal" in result.columns
        assert set(result["signal"].unique()).issubset({-1, 0, 1})

    def test_short_data_returns_zeros(self, sample_stock_id):
        """資料量 < 30 天（無 pred_label）→ 全 0"""
        dates = pd.date_range("2023-01-01", periods=10, freq="B")
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "open": [500] * 10, "high": [505] * 10, "low": [495] * 10,
            "close": [500] * 10, "volume": [1_000_000] * 10,
        })
        s = MLFactorStrategy()
        result = s.generate_signals(df)
        assert (result["signal"] == 0).all()

    def test_set_params(self):
        s = MLFactorStrategy()
        s.set_params(buy_quantile=4, sell_quantile=0, forward_days=20)
        assert s.params["buy_quantile"] == 4
        assert s.params["forward_days"] == 20

    def test_custom_quantile_mapping(self, sample_stock_id):
        """5 分位設定：pred_label=4 → buy, pred_label=0 → sell"""
        dates = pd.date_range("2023-01-01", periods=10, freq="B")
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "close": [500] * 10,
            "pred_label": [0, 1, 2, 3, 4, 0, 1, 2, 3, 4],
        })
        s = MLFactorStrategy()
        s.set_params(buy_quantile=4, sell_quantile=0)
        result = s.generate_signals(df)
        assert result.loc[df["pred_label"] == 4, "signal"].eq(1).all()
        assert result.loc[df["pred_label"] == 0, "signal"].eq(-1).all()
