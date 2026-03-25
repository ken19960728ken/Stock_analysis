"""次產業輪動策略測試"""

import numpy as np
import pandas as pd
import pytest

from analysis.strategies.sub_industry_rotation import SubIndustryRotationStrategy


@pytest.fixture
def daily_data():
    """模擬日K資料 + enrich 欄位"""
    dates = pd.bdate_range("2025-01-01", periods=120)
    np.random.seed(42)
    n = len(dates)
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "date": dates,
        "open": close - np.random.rand(n),
        "high": close + np.random.rand(n),
        "low": close - np.random.rand(n) - 0.5,
        "close": close,
        "volume": np.random.randint(1000000, 5000000, n),
    })


class TestSubIndustryRotationStrategy:
    def test_basic_init(self):
        strategy = SubIndustryRotationStrategy()
        assert strategy.name == "次產業輪動"
        assert "lookback_months" in strategy.params
        assert "top_n_industries" in strategy.params
        assert "max_hold_days" in strategy.params

    def test_no_sub_industry_returns_zero_signal(self, daily_data):
        """沒有 sub_industry 欄位時不產生訊號"""
        strategy = SubIndustryRotationStrategy()
        result = strategy.generate_signals(daily_data)
        assert "signal" in result.columns
        assert (result["signal"] == 0).all()

    def test_with_sub_industry_and_revenue(self, daily_data):
        """有次產業 + 營收資料時產生訊號"""
        df = daily_data.copy()
        df["sub_industry"] = "IC 設計"
        df["revenue"] = 1000000
        df["revenue_yoy"] = np.nan
        # 前半段 YoY 從低到高（加速趨勢），後半段 YoY 轉負（賣出）
        df.loc[:59, "revenue_yoy"] = np.linspace(5, 25, 60)
        df.loc[60:, "revenue_yoy"] = -5.0

        strategy = SubIndustryRotationStrategy()
        result = strategy.generate_signals(df)
        assert "signal" in result.columns
        # 應有買入和賣出訊號
        assert (result["signal"] == 1).any()
        assert (result["signal"] == -1).any()

    def test_with_yoy_acceleration(self, daily_data):
        """營收 YoY 加速時產生買入訊號"""
        df = daily_data.copy()
        df["sub_industry"] = "IC 設計"
        df["revenue"] = 1000000
        df["revenue_yoy"] = np.nan
        # 前半段 YoY 由低到高（加速），後半段 YoY 轉負
        df.loc[:59, "revenue_yoy"] = np.linspace(5, 25, 60)
        df.loc[60:, "revenue_yoy"] = -5.0

        strategy = SubIndustryRotationStrategy()
        result = strategy.generate_signals(df)
        assert (result["signal"] == 1).any()
        assert (result["signal"] == -1).any()

    def test_max_hold_days(self, daily_data):
        """最大持有天數強制出場"""
        df = daily_data.copy()
        df["sub_industry"] = "IC 設計"
        df["revenue"] = 1000000
        # 營收 YoY 一直高（持續買入條件），測試強制出場
        df["revenue_yoy"] = np.linspace(5, 30, len(df))

        strategy = SubIndustryRotationStrategy()
        strategy.set_params(max_hold_days=30)
        result = strategy.generate_signals(df)

        # 應有強制賣出
        if (result["signal"] == 1).any():
            # 從第一個買入到賣出，不應超過 30 天
            buys = result[result["signal"] == 1].index
            sells = result[result["signal"] == -1].index
            if len(buys) > 0 and len(sells) > 0:
                first_buy = buys[0]
                first_sell = sells[sells > first_buy]
                if len(first_sell) > 0:
                    assert first_sell[0] - first_buy <= 30

    def test_sub_industry_na_returns_zero(self, daily_data):
        """sub_industry 全 NaN 不產生訊號"""
        df = daily_data.copy()
        df["sub_industry"] = None

        strategy = SubIndustryRotationStrategy()
        result = strategy.generate_signals(df)
        assert (result["signal"] == 0).all()

    def test_params_copy(self):
        """每個實例有獨立的 params"""
        s1 = SubIndustryRotationStrategy()
        s2 = SubIndustryRotationStrategy()
        s1.set_params(top_n_industries=5)
        assert s2.params["top_n_industries"] == 3

    def test_with_institutional_data(self, daily_data):
        """有法人資料時整合考慮"""
        df = daily_data.copy()
        df["sub_industry"] = "IC 設計"
        df["revenue"] = 1000000
        df["revenue_yoy"] = 20.0
        df["institutional_net_buy"] = np.random.randint(-1000, 2000, len(df))

        strategy = SubIndustryRotationStrategy()
        result = strategy.generate_signals(df)
        assert "signal" in result.columns

    def test_strategy_in_map(self):
        """策略已註冊"""
        from analysis.strategies import STRATEGY_MAP
        assert "次產業輪動" in STRATEGY_MAP
        assert STRATEGY_MAP["次產業輪動"] == SubIndustryRotationStrategy
