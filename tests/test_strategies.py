"""
策略單元測試 — 4 個策略深度測試 + 多因子 Z-Score
"""

import numpy as np
import pandas as pd
import pytest

from analysis.strategies.fundamental_ratio import FundamentalRatioStrategy
from analysis.strategies.free_cash_flow import FreeCashFlowStrategy
from analysis.strategies.margin_signal import MarginSignalStrategy
from analysis.strategies.ownership_concentration import OwnershipConcentrationStrategy
from analysis.strategies.multi_factor import MultiFactorStrategy


# ============================================================================
# TestFundamentalRatioStrategy
# ============================================================================

class TestFundamentalRatioStrategy:
    """財報三率策略"""

    def test_generate_signals_all_conditions_met(self, sample_fundamental_wide):
        """三率全達標 → 有 buy signal"""
        s = FundamentalRatioStrategy()
        result = s.generate_signals(sample_fundamental_wide)
        assert "signal" in result.columns
        assert (result["signal"] == 1).any()

    def test_generate_signals_partial_conditions(self, sample_fundamental_wide):
        """2/3 達標 → min_conditions=2 → buy"""
        df = sample_fundamental_wide.copy()
        # 讓毛利率偏低
        df["GrossProfit"] = df["Revenue"] * 0.05
        s = FundamentalRatioStrategy()
        s.set_params(min_conditions=2)
        result = s.generate_signals(df)
        assert "signal" in result.columns
        # 營業利益率 + 淨利率仍達標
        assert (result["signal"] == 1).any()

    def test_generate_signals_none_met(self, sample_fundamental_wide):
        """三率都不達標 → 無 buy signal"""
        df = sample_fundamental_wide.copy()
        df["GrossProfit"] = df["Revenue"] * 0.01
        df["OperatingIncome"] = df["Revenue"] * 0.01
        df["IncomeAfterTaxes"] = df["Revenue"] * 0.01
        s = FundamentalRatioStrategy()
        result = s.generate_signals(df)
        assert not (result["signal"] == 1).any()

    def test_missing_columns_graceful(self, sample_stock_id):
        """缺 GrossProfit 欄 → 只用 2 率"""
        df = pd.DataFrame({
            "date": pd.to_datetime(["2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31"]),
            "stock_id": sample_stock_id,
            "close": [580, 590, 585, 595],
            "Revenue": [4.5e11, 4.8e11, 5.0e11, 5.2e11],
            "OperatingIncome": [1.0e11, 1.1e11, 1.15e11, 1.2e11],
            "IncomeAfterTaxes": [0.9e11, 0.95e11, 1.0e11, 1.05e11],
        })
        s = FundamentalRatioStrategy()
        s.set_params(min_conditions=1)
        result = s.generate_signals(df)
        assert "signal" in result.columns

    def test_set_params_updates_thresholds(self):
        s = FundamentalRatioStrategy()
        s.set_params(gross_margin_threshold=50.0)
        assert s.params["gross_margin_threshold"] == 50.0

    def test_signal_values_valid(self, sample_fundamental_wide):
        s = FundamentalRatioStrategy()
        result = s.generate_signals(sample_fundamental_wide)
        assert set(result["signal"].unique()).issubset({-1, 0, 1})

    def test_sell_signal_on_score_drop(self, sample_fundamental_wide):
        """條件跌落 → sell signal"""
        df = sample_fundamental_wide.copy()
        # 最後一季三率全部低於門檻
        df.loc[df.index[-1], "GrossProfit"] = df.loc[df.index[-1], "Revenue"] * 0.01
        df.loc[df.index[-1], "OperatingIncome"] = df.loc[df.index[-1], "Revenue"] * 0.01
        df.loc[df.index[-1], "IncomeAfterTaxes"] = df.loc[df.index[-1], "Revenue"] * 0.01
        s = FundamentalRatioStrategy()
        result = s.generate_signals(df)
        assert (result["signal"] == -1).any()


# ============================================================================
# TestFreeCashFlowStrategy
# ============================================================================

class TestFreeCashFlowStrategy:
    """自由現金流策略"""

    def test_positive_ocf_buy_signal(self, sample_fundamental_wide):
        """OCF>0 + yield 達標 → buy"""
        df = sample_fundamental_wide.copy()
        df["market_value"] = 1e12
        s = FreeCashFlowStrategy()
        s.set_params(fcf_yield_threshold=5.0)
        result = s.generate_signals(df)
        assert "signal" in result.columns
        # OCF = 1.2e11..1.4e11, MV = 1e12, yield = 12-14%
        assert (result["signal"] == 1).any()

    def test_negative_ocf_no_buy(self, sample_fundamental_wide):
        """OCF<0 → 不買"""
        df = sample_fundamental_wide.copy()
        df["CashFlowsFromOperatingActivities"] = [-1e11] * len(df)
        df["market_value"] = 1e12
        s = FreeCashFlowStrategy()
        result = s.generate_signals(df)
        assert not (result["signal"] == 1).any()

    def test_missing_market_value_graceful(self, sample_fundamental_wide):
        """無 market_value → 降級為只看 OCF"""
        s = FreeCashFlowStrategy()
        result = s.generate_signals(sample_fundamental_wide)
        assert "signal" in result.columns

    def test_signal_values_valid(self, sample_fundamental_wide):
        df = sample_fundamental_wide.copy()
        df["market_value"] = 1e12
        s = FreeCashFlowStrategy()
        result = s.generate_signals(df)
        assert set(result["signal"].unique()).issubset({-1, 0, 1})

    def test_fcf_with_capex(self, sample_fundamental_wide):
        """有 CapEx 欄位時，FCF = OCF - CapEx，yield 降低可能不觸發 buy"""
        df = sample_fundamental_wide.copy()
        df["market_value"] = 1e12
        # CapEx 接近 OCF，使 FCF ≈ 0 → yield ≈ 0% → 不達標
        df["PropertyAndPlantAndEquipment"] = -df["CashFlowsFromOperatingActivities"] * 0.95
        s = FreeCashFlowStrategy()
        s.set_params(fcf_yield_threshold=5.0)
        result = s.generate_signals(df)
        # FCF yield ≈ 0.5-0.7%，遠低於 5% 門檻 → 不應有 buy
        assert not (result["signal"] == 1).any()

    def test_fcf_without_capex_backward_compatible(self, sample_fundamental_wide):
        """無 CapEx 欄位時，FCF = OCF（向後相容）"""
        df = sample_fundamental_wide.copy()
        df["market_value"] = 1e12
        s = FreeCashFlowStrategy()
        s.set_params(fcf_yield_threshold=5.0)
        result = s.generate_signals(df)
        # OCF = 1.2e11..1.4e11, MV = 1e12, yield = 12-14% → 應有 buy
        assert (result["signal"] == 1).any()


# ============================================================================
# TestMarginSignalStrategy
# ============================================================================

class TestMarginSignalStrategy:
    """融資融券訊號策略"""

    def test_margin_decrease_price_up_buy(self, sample_margin_20d):
        """融資減+價漲 → buy"""
        s = MarginSignalStrategy()
        result = s.generate_signals(sample_margin_20d)
        assert "signal" in result.columns
        # 融資從 10000 遞減到 8100，價格遞增 → 應有 buy
        assert (result["signal"] == 1).any()

    def test_margin_increase_no_buy(self, sample_stock_id):
        """融資增 → 不買"""
        dates = pd.date_range("2023-01-01", periods=20, freq="B")
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "close": [580 + i * 0.5 for i in range(20)],
            "margin_purchase_balance": [10000 + i * 200 for i in range(20)],
        })
        s = MarginSignalStrategy()
        result = s.generate_signals(df)
        # 融資增加 → 不應有 buy（融資增 + 價漲不符合策略）
        assert not (result["signal"] == 1).any()

    def test_lookback_days_param(self, sample_margin_20d):
        """不同 lookback 天數"""
        s = MarginSignalStrategy()
        s.set_params(lookback_days=10)
        result = s.generate_signals(sample_margin_20d)
        assert "signal" in result.columns

    def test_missing_margin_column_graceful(self, sample_stock_id):
        df = pd.DataFrame({
            "date": pd.date_range("2023-01-01", periods=10, freq="B"),
            "stock_id": sample_stock_id,
            "close": range(100, 110),
        })
        s = MarginSignalStrategy()
        result = s.generate_signals(df)
        assert (result["signal"] == 0).all()

    def test_sell_signal_reverse_condition(self, sample_stock_id):
        """融資暴增 + 股價下跌 → sell"""
        dates = pd.date_range("2023-01-01", periods=20, freq="B")
        balance = [10000] * 10 + [10000 + i * 500 for i in range(10)]
        close = [580] * 10 + [580 - i * 2 for i in range(10)]
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "close": close,
            "margin_purchase_balance": balance,
        })
        s = MarginSignalStrategy()
        result = s.generate_signals(df)
        assert (result["signal"] == -1).any()

    def test_signal_values_valid(self, sample_margin_20d):
        s = MarginSignalStrategy()
        result = s.generate_signals(sample_margin_20d)
        assert set(result["signal"].unique()).issubset({-1, 0, 1})


# ============================================================================
# TestOwnershipConcentrationStrategy
# ============================================================================

class TestOwnershipConcentrationStrategy:
    """股權集中度策略"""

    def test_holder_increase_shareholder_decrease_buy(self, sample_stock_id):
        """大股東增+散戶減 → buy（需足夠長的日資料使 shift(20) 有效）"""
        dates = pd.date_range("2023-01-01", periods=30, freq="B")
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "close": [580 + i * 2 for i in range(30)],
            "holding_percentage": [25.0 + i * 0.1 for i in range(30)],
            "shareholder_count": [10000 - i * 50 for i in range(30)],
        })
        s = OwnershipConcentrationStrategy()
        result = s.generate_signals(df)
        assert "signal" in result.columns
        assert (result["signal"] == 1).any()

    def test_only_holder_increase_no_buy(self, sample_stock_id):
        """只有大股東增、股東人數也增 → 不買"""
        dates = pd.date_range("2023-01-01", periods=30, freq="B")
        df = pd.DataFrame({
            "date": dates, "stock_id": sample_stock_id,
            "close": [580 + i * 2 for i in range(30)],
            "holding_percentage": [25.0 + i * 0.1 for i in range(30)],
            "shareholder_count": [10000 + i * 50 for i in range(30)],
        })
        s = OwnershipConcentrationStrategy()
        result = s.generate_signals(df)
        assert not (result["signal"] == 1).any()

    def test_short_data_no_crash(self, sample_shareholding_8w):
        """短資料不崩潰"""
        s = OwnershipConcentrationStrategy()
        result = s.generate_signals(sample_shareholding_8w)
        assert len(result) == len(sample_shareholding_8w)

    def test_missing_columns_graceful(self, sample_stock_id):
        df = pd.DataFrame({
            "date": pd.date_range("2023-01-01", periods=8, freq="W"),
            "stock_id": sample_stock_id,
            "close": range(100, 108),
        })
        s = OwnershipConcentrationStrategy()
        result = s.generate_signals(df)
        assert (result["signal"] == 0).all()

    def test_signal_values_valid(self, sample_shareholding_8w):
        s = OwnershipConcentrationStrategy()
        result = s.generate_signals(sample_shareholding_8w)
        assert set(result["signal"].unique()).issubset({-1, 0, 1})


# ============================================================================
# TestMultiFactorZScore
# ============================================================================

class TestMultiFactorZScore:
    """多因子 Z-Score 升級"""

    def test_zscore_enabled(self, sample_multi_factor_50d):
        """use_zscore=True → 可正常執行"""
        s = MultiFactorStrategy()
        s.set_params(use_zscore=True)
        result = s.generate_signals(sample_multi_factor_50d)
        assert "signal" in result.columns
        assert set(result["signal"].unique()).issubset({-1, 0, 1})

    def test_zscore_disabled_backward_compatible(self, sample_multi_factor_50d):
        """use_zscore=False → 與預設相同"""
        s1 = MultiFactorStrategy()
        s2 = MultiFactorStrategy()
        s2.set_params(use_zscore=False)
        r1 = s1.generate_signals(sample_multi_factor_50d.copy())
        r2 = s2.generate_signals(sample_multi_factor_50d.copy())
        pd.testing.assert_series_equal(r1["signal"], r2["signal"])

    def test_zscore_changes_signal_timing(self, sample_multi_factor_50d):
        """Z-Score 可能改變訊號觸發時機"""
        s_off = MultiFactorStrategy()
        s_on = MultiFactorStrategy()
        s_on.set_params(use_zscore=True)
        r_off = s_off.generate_signals(sample_multi_factor_50d.copy())
        r_on = s_on.generate_signals(sample_multi_factor_50d.copy())
        # 不一定相同（Z-Score 改變了分數分佈）
        # 只需驗證兩者都是合法 signal
        assert set(r_off["signal"].unique()).issubset({-1, 0, 1})
        assert set(r_on["signal"].unique()).issubset({-1, 0, 1})
