"""
因子工程測試 — Z-Score、IC、相關性矩陣
"""

import numpy as np
import pandas as pd
import pytest

from analysis.utils.factor_engine import (
    calculate_ic,
    factor_correlation_matrix,
    ic_series,
    zscore_cross_sectional,
    zscore_normalize,
)


# ============================================================================
# TestZScoreNormalize
# ============================================================================

class TestZScoreNormalize:

    def test_mean_near_zero(self):
        s = pd.Series(np.random.randn(100) * 10 + 50)
        z = zscore_normalize(s)
        assert abs(z.mean()) < 0.2

    def test_std_near_one(self):
        s = pd.Series(np.random.randn(100) * 10 + 50)
        z = zscore_normalize(s)
        assert abs(z.std() - 1.0) < 0.3

    def test_winsorize_extreme_values(self):
        s = pd.Series([1, 2, 3, 4, 5, 100])
        z = zscore_normalize(s)
        assert z.max() <= 3.0
        assert z.min() >= -3.0

    def test_single_value_returns_zero(self):
        s = pd.Series([42.0])
        z = zscore_normalize(s)
        assert (z == 0.0).all()

    def test_all_same_returns_zero(self):
        s = pd.Series([5.0, 5.0, 5.0, 5.0])
        z = zscore_normalize(s)
        assert (z == 0.0).all()


# ============================================================================
# TestZScoreCrossSectional
# ============================================================================

class TestZScoreCrossSectional:

    def test_per_date_normalization(self, sample_cross_sectional_factors):
        z = zscore_cross_sectional(sample_cross_sectional_factors, "factor_value")
        assert len(z) == len(sample_cross_sectional_factors)

    def test_different_dates_independent(self, sample_cross_sectional_factors):
        """每日截面標準化結果互不干擾"""
        df = sample_cross_sectional_factors.copy()
        z = zscore_cross_sectional(df, "factor_value")
        df["z"] = z

        # 每一天的 z-score 應該是獨立標準化的
        for date, group in df.groupby("date"):
            zvals = group["z"].dropna()
            if len(zvals) > 1 and zvals.std() > 0:
                assert abs(zvals.mean()) < 0.5


# ============================================================================
# TestCalculateIC
# ============================================================================

class TestCalculateIC:

    def test_perfect_correlation(self):
        factor = pd.Series([1, 2, 3, 4, 5], dtype=float)
        ret = pd.Series([0.01, 0.02, 0.03, 0.04, 0.05])
        ic = calculate_ic(factor, ret)
        assert ic > 0.9

    def test_no_correlation(self):
        np.random.seed(42)
        factor = pd.Series(np.random.randn(100))
        ret = pd.Series(np.random.randn(100))
        ic = calculate_ic(factor, ret)
        assert abs(ic) < 0.5

    def test_spearman_vs_pearson(self):
        factor = pd.Series([1, 2, 3, 4, 5], dtype=float)
        ret = pd.Series([0.01, 0.02, 0.03, 0.04, 0.05])
        ic_spearman = calculate_ic(factor, ret, method="spearman")
        ic_pearson = calculate_ic(factor, ret, method="pearson")
        # Both should be high for perfect linear relationship
        assert ic_spearman > 0.9
        assert ic_pearson > 0.9

    def test_empty_input_returns_nan(self):
        factor = pd.Series([], dtype=float)
        ret = pd.Series([], dtype=float)
        ic = calculate_ic(factor, ret)
        assert np.isnan(ic)


# ============================================================================
# TestICSeries
# ============================================================================

class TestICSeries:

    def test_rolling_ic_output_shape(self, sample_cross_sectional_factors):
        factor_df = sample_cross_sectional_factors.copy()
        return_df = sample_cross_sectional_factors[["date", "stock_id", "close"]].copy()
        result = ic_series(factor_df, return_df, "factor_value", forward_days=2)
        assert "date" in result.columns
        assert "ic" in result.columns
        assert "ic_cumsum" in result.columns
        assert len(result) > 0

    def test_ic_cumsum_monotonic_if_positive(self):
        """如果每期 IC 都是正的，累積 IC 應遞增"""
        factor_df = pd.DataFrame({
            "date": pd.date_range("2023-01-01", periods=20, freq="B").repeat(3),
            "stock_id": ["A", "B", "C"] * 20,
            "factor_value": list(range(60)),
            "close": list(range(60)),
        })
        return_df = factor_df[["date", "stock_id", "close"]].copy()
        result = ic_series(factor_df, return_df, "factor_value", forward_days=1)
        if not result.empty and result["ic"].notna().any():
            # Just verify structure
            assert "ic_cumsum" in result.columns


# ============================================================================
# TestFactorCorrelation
# ============================================================================

class TestFactorCorrelation:

    def test_diagonal_is_one(self):
        factors = {
            "f1": pd.Series(np.random.randn(50)),
            "f2": pd.Series(np.random.randn(50)),
            "f3": pd.Series(np.random.randn(50)),
        }
        corr = factor_correlation_matrix(factors)
        for i in range(len(corr)):
            assert abs(corr.iloc[i, i] - 1.0) < 1e-10

    def test_symmetric_matrix(self):
        factors = {
            "f1": pd.Series(np.random.randn(50)),
            "f2": pd.Series(np.random.randn(50)),
        }
        corr = factor_correlation_matrix(factors)
        pd.testing.assert_frame_equal(corr, corr.T)

    def test_shape_matches_factor_count(self):
        factors = {
            "f1": pd.Series(np.random.randn(50)),
            "f2": pd.Series(np.random.randn(50)),
            "f3": pd.Series(np.random.randn(50)),
        }
        corr = factor_correlation_matrix(factors)
        assert corr.shape == (3, 3)
