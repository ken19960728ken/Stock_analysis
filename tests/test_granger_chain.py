"""Granger 因果供應鏈自動發現測試"""

import numpy as np
import pandas as pd
import pytest

from analysis.utils.granger_chain import build_industry_series, granger_pairwise


@pytest.fixture
def sample_industry_map():
    return pd.DataFrame({
        "stock_id": ["2330", "2317", "2454", "2881", "2882", "2412"],
        "industry_category": ["半導體", "半導體", "半導體", "金融", "金融", "電信"],
        "sector": ["半導體業", "半導體業", "半導體業", "金融業", "金融業", "電信業"],
        "sub_industry": ["IC 設計", "IC 製造", "IC 設計", "銀行", "銀行", "電信"],
    })


@pytest.fixture
def sample_revenue_df():
    """12 個月 × 6 支股票"""
    dates = pd.date_range("2023-01-01", periods=12, freq="MS")
    rows = []
    for d in dates:
        for sid, yoy in [("2330", 15.0), ("2317", 10.0), ("2454", 20.0),
                         ("2881", 5.0), ("2882", 3.0), ("2412", 8.0)]:
            rows.append({
                "stock_id": sid,
                "date": d,
                "revenue": 1e9,
                "month_revenue_year_on_year": yoy + np.random.randn() * 2,
            })
    return pd.DataFrame(rows)


class TestBuildIndustrySeries:
    def test_returns_dict_of_series(self, sample_revenue_df, sample_industry_map):
        result = build_industry_series(sample_revenue_df, sample_industry_map)
        assert isinstance(result, dict)
        assert len(result) > 0
        for key, series in result.items():
            assert isinstance(series, pd.Series)
            assert isinstance(key, str)

    def test_correct_sub_industries(self, sample_revenue_df, sample_industry_map):
        result = build_industry_series(sample_revenue_df, sample_industry_map)
        assert "IC 設計" in result
        assert "IC 製造" in result
        assert "銀行" in result

    def test_empty_input(self, sample_industry_map):
        result = build_industry_series(pd.DataFrame(), sample_industry_map)
        assert result == {}


@pytest.fixture
def causal_series():
    """構造有因果關係的時間序列：A 領先 B 兩期"""
    np.random.seed(42)
    n = 36
    a = np.cumsum(np.random.randn(n))
    b = np.zeros(n)
    b[2:] = a[:-2] + np.random.randn(n - 2) * 0.3  # B 滯後 A 兩期
    months = pd.period_range("2021-01", periods=n, freq="M")
    return {
        "A": pd.Series(a, index=months),
        "B": pd.Series(b, index=months),
    }


class TestGrangerPairwise:
    def test_detects_causal_pair(self, causal_series):
        result = granger_pairwise(causal_series, max_lag=3, p_threshold=0.10)
        assert not result.empty
        assert set(result.columns) >= {"source", "target", "lag", "f_stat", "p_value"}
        # A 應 Granger-cause B
        ab = result[(result["source"] == "A") & (result["target"] == "B")]
        assert not ab.empty

    def test_no_signal_independent_noise(self):
        """獨立噪音序列不應產生顯著因果"""
        np.random.seed(123)
        n = 36
        months = pd.period_range("2021-01", periods=n, freq="M")
        series = {
            "X": pd.Series(np.random.randn(n), index=months),
            "Y": pd.Series(np.random.randn(n), index=months),
        }
        result = granger_pairwise(series, max_lag=3, p_threshold=0.01)
        # 嚴格 p < 0.01 下，獨立噪音很少顯著
        assert len(result) <= 1  # 容許偶發 false positive

    def test_insufficient_data(self):
        """資料不足應回傳空"""
        months = pd.period_range("2021-01", periods=3, freq="M")
        series = {
            "A": pd.Series([1, 2, 3], index=months),
            "B": pd.Series([4, 5, 6], index=months),
        }
        result = granger_pairwise(series, max_lag=3, p_threshold=0.05)
        assert result.empty
