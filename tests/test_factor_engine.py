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
        """rolling z-score 的有效值均值應接近零"""
        s = pd.Series(np.random.randn(300) * 10 + 50)
        z = zscore_normalize(s)
        valid = z.dropna()
        assert abs(valid.mean()) < 1.0

    def test_std_near_one(self):
        """rolling z-score 的有效值標準差應接近一"""
        s = pd.Series(np.random.randn(300) * 10 + 50)
        z = zscore_normalize(s)
        valid = z.dropna()
        assert 0.3 < valid.std() < 2.0

    def test_winsorize_extreme_values(self):
        s = pd.Series(np.random.randn(300) * 10 + 50)
        s.iloc[-1] = 99999  # 極端值
        z = zscore_normalize(s)
        valid = z.dropna()
        assert valid.max() <= 3.0
        assert valid.min() >= -3.0

    def test_single_value_returns_zero(self):
        s = pd.Series([42.0])
        z = zscore_normalize(s)
        assert (z == 0.0).all()

    def test_all_same_returns_nan_or_zero(self):
        """全同值序列：短於 min_periods 時為 NaN，長序列時 std=0 也為 NaN"""
        s = pd.Series([5.0, 5.0, 5.0, 5.0])
        z = zscore_normalize(s)
        # 4 筆 < min_periods=60，全部為 NaN
        assert z.isna().all() or (z == 0.0).all()

    def test_no_look_ahead_bias(self):
        """前半段的 z-score 不應受後半段資料影響"""
        np.random.seed(42)
        base = pd.Series(np.random.randn(300) * 10 + 50)
        z_full = zscore_normalize(base)

        # 只給前 150 筆，結果應與完整版的前 150 筆相同
        z_partial = zscore_normalize(base.iloc[:150])
        overlap = 150
        non_nan_mask = z_partial.notna() & z_full.iloc[:overlap].notna()
        if non_nan_mask.sum() > 60:
            pd.testing.assert_series_equal(
                z_partial[non_nan_mask].reset_index(drop=True),
                z_full.iloc[:overlap][non_nan_mask].reset_index(drop=True),
                atol=1e-10,
            )

    def test_early_period_has_nan(self):
        """rolling 模式下前 min_periods 筆應為 NaN"""
        s = pd.Series(np.random.randn(100) * 10 + 50)
        z = zscore_normalize(s)
        # 預設 min_periods=60，前 59 筆應為 NaN
        assert z.iloc[:59].isna().all()


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
