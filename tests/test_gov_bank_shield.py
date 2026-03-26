"""
官股護盤偵測策略 — 單元測試（8 項）

測試:
1. 無 gov_net 時 signal 全 0
2. intensity > 1.3 + 跌 > 1% 時買入
3. intensity < 1.3 不觸發
4. 上漲日不觸發
5. 持有到期自動賣出
6. bank_count < min_banks 不觸發
7. 在 STRATEGY_MAP 中已註冊
8. 預設參數正確
"""

import numpy as np
import pandas as pd
import pytest

from analysis.strategies.gov_bank_shield import GovBankShieldStrategy


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def base_df():
    """100 天 DataFrame，含下跌段 + 官股資料"""
    np.random.seed(42)
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, freq="B")

    # 建立有下跌段的價格序列
    close = np.full(n, 100.0)
    for i in range(1, n):
        if 40 <= i <= 50:
            # 下跌段：每天跌約 1.5%
            close[i] = close[i - 1] * 0.985
        else:
            close[i] = close[i - 1] * (1 + np.random.normal(0.001, 0.005))

    # 官股淨買超：平常約 5000，下跌段放大到 15000+
    gov_net = np.full(n, 5000.0)
    for i in range(40, 51):
        gov_net[i] = 15000.0 + np.random.normal(0, 500)

    return pd.DataFrame({
        "date": dates,
        "open": close - 0.5,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": np.random.randint(10_000_000, 50_000_000, n),
        "gov_net": gov_net,
        "gov_bank_count": np.full(n, 8),
    })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGovBankShield:

    def test_no_gov_data_returns_no_signal(self):
        """無 gov_net 欄位時，signal 全為 0"""
        n = 50
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        df = pd.DataFrame({
            "date": dates,
            "open": np.arange(100, 100 + n, dtype=float),
            "high": np.arange(101, 101 + n, dtype=float),
            "low": np.arange(99, 99 + n, dtype=float),
            "close": np.arange(100, 100 + n, dtype=float),
            "volume": np.full(n, 10_000_000),
        })
        strategy = GovBankShieldStrategy()
        result = strategy.generate_signals(df)
        assert (result["signal"] == 0).all()

    def test_buy_on_high_intensity_and_drop(self, base_df):
        """intensity > 1.3 + 跌 > 1% 應觸發買入"""
        strategy = GovBankShieldStrategy()
        result = strategy.generate_signals(base_df)
        buy_signals = result[result["signal"] == 1]
        # 下跌段（index 40-50）中應有買入訊號
        assert len(buy_signals) > 0
        # 買入應在下跌段內
        buy_indices = buy_signals.index.tolist()
        assert any(40 <= idx <= 55 for idx in buy_indices)

    def test_no_buy_on_normal_intensity(self):
        """intensity < 1.3（官股買超力道正常）不應觸發"""
        n = 60
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        # 穩定下跌但官股買超力道不變
        close = np.array([100.0 - i * 0.5 for i in range(n)])
        df = pd.DataFrame({
            "date": dates,
            "open": close + 0.5,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": np.full(n, 10_000_000),
            "gov_net": np.full(n, 5000.0),  # 力道恆定，intensity ~= 1.0
            "gov_bank_count": np.full(n, 8),
        })
        strategy = GovBankShieldStrategy()
        result = strategy.generate_signals(df)
        # intensity 約 1.0，不超過 1.3，不應觸發
        assert (result["signal"] == 0).all()

    def test_no_buy_on_up_day(self):
        """上漲日即使 intensity 高也不觸發"""
        n = 60
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        # 持續上漲
        close = np.array([100.0 + i * 2 for i in range(n)])
        gov_net = np.full(n, 5000.0)
        gov_net[30:35] = 20000.0  # 力道放大但是上漲中
        df = pd.DataFrame({
            "date": dates,
            "open": close - 0.5,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": np.full(n, 10_000_000),
            "gov_net": gov_net,
            "gov_bank_count": np.full(n, 8),
        })
        strategy = GovBankShieldStrategy()
        result = strategy.generate_signals(df)
        assert (result["signal"] == 0).all()

    def test_max_hold_days_exit(self, base_df):
        """持有達 max_hold_days 天後應產生 -1 賣出訊號"""
        strategy = GovBankShieldStrategy()
        strategy.set_params(max_hold_days=5)
        result = strategy.generate_signals(base_df)

        buy_indices = result.index[result["signal"] == 1].tolist()
        sell_indices = result.index[result["signal"] == -1].tolist()

        if buy_indices:
            # 應有對應賣出
            assert len(sell_indices) > 0
            # 第一個賣出應在第一個買入後約 5 天
            first_buy = buy_indices[0]
            first_sell = sell_indices[0]
            assert first_sell - first_buy == 5

    def test_min_banks_filter(self, base_df):
        """bank_count < min_banks 時不應觸發"""
        df = base_df.copy()
        df["gov_bank_count"] = 3  # 低於預設 min_banks=6
        strategy = GovBankShieldStrategy()
        result = strategy.generate_signals(df)
        assert (result["signal"] == 0).all()

    def test_strategy_registered(self):
        """策略應在 STRATEGY_MAP 中"""
        from analysis.strategies import STRATEGY_MAP
        assert "官股護盤" in STRATEGY_MAP

    def test_params_default(self):
        """預設參數正確"""
        strategy = GovBankShieldStrategy()
        params = strategy.get_params()
        assert params["intensity_threshold"] == 1.3
        assert params["market_drop_pct"] == -0.01
        assert params["lookback_days"] == 20
        assert params["max_hold_days"] == 20
        assert params["min_banks"] == 6
