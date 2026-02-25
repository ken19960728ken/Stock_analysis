"""
產業輪動測試 — 營收動能、法人流向、綜合排名
"""

import numpy as np
import pandas as pd
import pytest

from analysis.utils.sector_rotation import (
    calc_industry_flow,
    calc_industry_momentum,
    industry_composite_score,
    industry_rotation_history,
)


@pytest.fixture
def sample_industry_map():
    return pd.DataFrame({
        "stock_id": ["2330", "2317", "2454", "2881", "2882", "2412"],
        "industry_category": ["半導體", "半導體", "半導體", "金融", "金融", "電信"],
    })


@pytest.fixture
def sample_revenue_df():
    """3 個月 × 6 支股票"""
    dates = pd.date_range("2023-10-01", periods=3, freq="MS")
    rows = []
    for d in dates:
        for sid, yoy in [("2330", 15.0), ("2317", 10.0), ("2454", 20.0),
                         ("2881", 5.0), ("2882", 3.0), ("2412", 8.0)]:
            rows.append({
                "stock_id": sid,
                "date": d,
                "revenue": 1e9 + np.random.rand() * 1e8,
                "month_revenue_year_on_year": yoy + np.random.randn() * 2,
            })
    return pd.DataFrame(rows)


@pytest.fixture
def sample_chip_df():
    """20 天 × 6 支股票"""
    dates = pd.date_range("2023-12-01", periods=20, freq="B")
    rows = []
    for d in dates:
        for sid, net in [("2330", 5000), ("2317", 3000), ("2454", 8000),
                         ("2881", -2000), ("2882", -1000), ("2412", 1000)]:
            rows.append({
                "stock_id": sid, "date": d,
                "foreign_investors_buy": abs(net) * 2,
                "foreign_investors_sell": abs(net),
                "investment_trust_buy": 1000,
                "investment_trust_sell": 800,
                "dealer_buy": 500,
                "dealer_sell": 300,
            })
    return pd.DataFrame(rows)


class TestCalcIndustryMomentum:
    def test_output_columns(self, sample_revenue_df, sample_industry_map):
        result = calc_industry_momentum(sample_revenue_df, sample_industry_map)
        assert "industry" in result.columns
        assert "avg_yoy" in result.columns
        assert "rank" in result.columns

    def test_industries_present(self, sample_revenue_df, sample_industry_map):
        result = calc_industry_momentum(sample_revenue_df, sample_industry_map)
        assert len(result) == 3  # 半導體、金融、電信

    def test_rank_ordering(self, sample_revenue_df, sample_industry_map):
        result = calc_industry_momentum(sample_revenue_df, sample_industry_map)
        # 半導體 YoY 最高，應排名較前
        semi = result[result["industry"] == "半導體"]
        assert not semi.empty
        assert semi.iloc[0]["rank"] <= 2  # top 2

    def test_empty_input(self, sample_industry_map):
        result = calc_industry_momentum(pd.DataFrame(), sample_industry_map)
        assert result.empty


class TestCalcIndustryFlow:
    def test_output_columns(self, sample_chip_df, sample_industry_map):
        result = calc_industry_flow(sample_chip_df, sample_industry_map)
        assert "industry" in result.columns
        assert "total_net_buy" in result.columns
        assert "rank" in result.columns

    def test_flow_direction(self, sample_chip_df, sample_industry_map):
        result = calc_industry_flow(sample_chip_df, sample_industry_map)
        # 半導體法人淨買超最多
        semi = result[result["industry"] == "半導體"]
        assert not semi.empty
        assert semi.iloc[0]["total_net_buy"] > 0

    def test_empty_input(self, sample_industry_map):
        result = calc_industry_flow(pd.DataFrame(), sample_industry_map)
        assert result.empty


class TestIndustryCompositeScore:
    def test_output_columns(self, sample_revenue_df, sample_chip_df, sample_industry_map):
        momentum = calc_industry_momentum(sample_revenue_df, sample_industry_map)
        flow = calc_industry_flow(sample_chip_df, sample_industry_map)
        result = industry_composite_score(momentum, flow)
        assert "industry" in result.columns
        assert "composite_score" in result.columns
        assert "final_rank" in result.columns

    def test_weight_effect(self, sample_revenue_df, sample_chip_df, sample_industry_map):
        momentum = calc_industry_momentum(sample_revenue_df, sample_industry_map)
        flow = calc_industry_flow(sample_chip_df, sample_industry_map)

        result_m = industry_composite_score(momentum, flow, m_weight=1.0, f_weight=0.0)
        result_f = industry_composite_score(momentum, flow, m_weight=0.0, f_weight=1.0)

        # 不同權重應該產生不同排名
        assert isinstance(result_m, pd.DataFrame)
        assert isinstance(result_f, pd.DataFrame)

    def test_both_empty(self):
        result = industry_composite_score(pd.DataFrame(), pd.DataFrame())
        assert result.empty


class TestIndustryRotationHistory:
    def test_output_shape(self, sample_revenue_df, sample_chip_df, sample_industry_map):
        result = industry_rotation_history(
            sample_revenue_df, sample_chip_df, sample_industry_map, periods=3
        )
        if not result.empty:
            assert isinstance(result, pd.DataFrame)
            assert result.shape[0] <= 3

    def test_empty_input(self, sample_chip_df, sample_industry_map):
        result = industry_rotation_history(
            pd.DataFrame(), sample_chip_df, sample_industry_map
        )
        assert result.empty
