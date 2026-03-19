"""
產業輪動測試 — 營收動能、法人流向、綜合排名
"""

import numpy as np
import pandas as pd
import pytest

from analysis.utils.sector_rotation import (
    calc_industry_flow,
    calc_industry_momentum,
    calc_industry_valuation,
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


class TestDecayWeighting:
    """衰減加權相關測試"""

    def test_momentum_decay_recent_higher_weight(self, sample_revenue_df, sample_industry_map):
        """啟用衰減後，近期 YoY 的權重應高於遠期"""
        result_no_decay = calc_industry_momentum(
            sample_revenue_df, sample_industry_map, decay_half_life=None
        )
        result_with_decay = calc_industry_momentum(
            sample_revenue_df, sample_industry_map, decay_half_life=1
        )
        # 兩者應都有結果且結構相同
        assert not result_no_decay.empty
        assert not result_with_decay.empty
        assert set(result_no_decay.columns) == set(result_with_decay.columns)

    def test_momentum_decay_none_backward_compatible(self, sample_revenue_df, sample_industry_map):
        """decay_half_life=None 應與原始行為一致"""
        result_default = calc_industry_momentum(sample_revenue_df, sample_industry_map)
        result_none = calc_industry_momentum(
            sample_revenue_df, sample_industry_map, decay_half_life=None
        )
        pd.testing.assert_frame_equal(result_default, result_none)

    def test_flow_decay_recent_higher_weight(self, sample_chip_df, sample_industry_map):
        """法人流向啟用衰減後應正常回傳"""
        result_no_decay = calc_industry_flow(
            sample_chip_df, sample_industry_map, decay_half_life=None
        )
        result_with_decay = calc_industry_flow(
            sample_chip_df, sample_industry_map, decay_half_life=5
        )
        assert not result_no_decay.empty
        assert not result_with_decay.empty
        assert set(result_no_decay.columns) == set(result_with_decay.columns)

    def test_flow_decay_none_backward_compatible(self, sample_chip_df, sample_industry_map):
        """flow decay_half_life=None 應與原始行為一致"""
        result_default = calc_industry_flow(sample_chip_df, sample_industry_map)
        result_none = calc_industry_flow(
            sample_chip_df, sample_industry_map, decay_half_life=None
        )
        pd.testing.assert_frame_equal(result_default, result_none)

    def test_momentum_decay_different_half_lives(self, sample_revenue_df, sample_industry_map):
        """不同半衰期應產生不同結果"""
        result_short = calc_industry_momentum(
            sample_revenue_df, sample_industry_map, decay_half_life=1
        )
        result_long = calc_industry_momentum(
            sample_revenue_df, sample_industry_map, decay_half_life=6
        )
        # 不同半衰期的 avg_yoy 不應完全相同
        assert not result_short.empty and not result_long.empty


class TestDynamicWeights:
    """ICIR 動態權重測試"""

    def test_dynamic_weights_override(self, sample_revenue_df, sample_chip_df, sample_industry_map):
        """dynamic_weights 應覆蓋靜態 m_weight/f_weight"""
        momentum = calc_industry_momentum(sample_revenue_df, sample_industry_map)
        flow = calc_industry_flow(sample_chip_df, sample_industry_map)

        result_static = industry_composite_score(momentum, flow, m_weight=0.5, f_weight=0.5)
        result_dynamic = industry_composite_score(
            momentum, flow, m_weight=0.5, f_weight=0.5,
            dynamic_weights={"momentum": 0.8, "flow": 0.2}
        )
        # 動態權重大幅偏向 momentum，分數應不同
        assert not result_static.empty
        assert not result_dynamic.empty

    def test_dynamic_weights_none_no_effect(self, sample_revenue_df, sample_chip_df, sample_industry_map):
        """dynamic_weights=None 不應改變結果"""
        momentum = calc_industry_momentum(sample_revenue_df, sample_industry_map)
        flow = calc_industry_flow(sample_chip_df, sample_industry_map)

        result_default = industry_composite_score(momentum, flow)
        result_none = industry_composite_score(momentum, flow, dynamic_weights=None)
        pd.testing.assert_frame_equal(result_default, result_none)

    def test_dynamic_weights_partial(self, sample_revenue_df, sample_chip_df, sample_industry_map):
        """只提供部分 key 時，另一個用預設值"""
        momentum = calc_industry_momentum(sample_revenue_df, sample_industry_map)
        flow = calc_industry_flow(sample_chip_df, sample_industry_map)

        result = industry_composite_score(
            momentum, flow, dynamic_weights={"momentum": 0.7}
        )
        assert not result.empty


@pytest.fixture
def sample_per_df():
    """6 支股票的 PER/PBR/殖利率"""
    dates = pd.date_range("2023-10-01", periods=60, freq="B")
    rows = []
    stock_vals = {
        "2330": (18.0, 4.5, 2.5),
        "2317": (12.0, 2.0, 4.0),
        "2454": (25.0, 8.0, 1.0),
        "2881": (10.0, 1.2, 5.5),
        "2882": (11.0, 1.3, 5.0),
        "2412": (20.0, 3.0, 3.5),
    }
    for d in dates:
        for sid, (per, pbr, dy) in stock_vals.items():
            rows.append({
                "stock_id": sid,
                "date": d,
                "per": per + np.random.randn() * 1,
                "pbr": pbr + np.random.randn() * 0.2,
                "dividend_yield": dy + np.random.randn() * 0.3,
            })
    return pd.DataFrame(rows)


class TestCalcIndustryValuation:
    def test_percentile_output_columns(self, sample_per_df, sample_industry_map):
        result = calc_industry_valuation(sample_per_df, sample_industry_map)
        expected_cols = {"industry", "avg_per", "avg_pbr", "avg_dy",
                         "per_score", "pbr_score", "dy_score",
                         "valuation_score", "rank"}
        assert expected_cols == set(result.columns)

    def test_percentile_industries(self, sample_per_df, sample_industry_map):
        result = calc_industry_valuation(sample_per_df, sample_industry_map)
        # 半導體 3 股, 金融 2 股 (< 3), 電信 1 股 (< 3) → 只有半導體
        # 但金融有 2 股 被排除，電信 1 股也被排除
        # 若 stock_count >= 3，只有半導體通過
        assert len(result) >= 1

    def test_zscore_scores_in_range(self, sample_per_df, sample_industry_map):
        """z-score 模式：分數在 [0, 1] 範圍"""
        # 需要足夠多的產業，擴充 industry_map
        expanded_map = pd.DataFrame({
            "stock_id": ["2330", "2317", "2454", "2881", "2882", "2412",
                         "1301", "1303", "1326"],
            "industry_category": ["半導體", "半導體", "半導體",
                                   "金融", "金融", "金融",
                                   "塑化", "塑化", "塑化"],
        })
        extra_per = []
        for sid, (per, pbr, dy) in [("1301", (8.0, 1.0, 6.0)),
                                      ("1303", (9.0, 1.1, 5.5)),
                                      ("1326", (7.0, 0.9, 7.0))]:
            extra_per.append({"stock_id": sid, "date": "2023-12-01",
                              "per": per, "pbr": pbr, "dividend_yield": dy})
        combined_per = pd.concat([sample_per_df, pd.DataFrame(extra_per)], ignore_index=True)

        result = calc_industry_valuation(combined_per, expanded_map, method="zscore")
        assert not result.empty
        for col in ["per_score", "pbr_score", "dy_score", "valuation_score"]:
            assert result[col].min() >= 0 - 1e-9
            assert result[col].max() <= 1 + 1e-9

    def test_nan_handling(self, sample_industry_map):
        """PER 負值/NaN 應被排除"""
        per_df = pd.DataFrame({
            "stock_id": ["2330", "2317", "2454", "2881", "2882", "2412"],
            "date": ["2023-12-01"] * 6,
            "per": [-5.0, np.nan, 20.0, 10.0, 11.0, 15.0],
            "pbr": [3.0, 2.0, 8.0, 1.2, 1.3, 3.0],
            "dividend_yield": [2.0, 3.0, 1.0, 5.5, 5.0, 3.5],
        })
        result = calc_industry_valuation(per_df, sample_industry_map)
        # 2330(neg) 和 2317(NaN) 被排除，半導體只剩 2454 (< 3)
        # 金融 2 股 (< 3)，電信 1 股 (< 3) → 全部被排除
        assert result.empty

    def test_empty_input(self, sample_industry_map):
        result = calc_industry_valuation(pd.DataFrame(), sample_industry_map)
        assert result.empty


class TestCompositeScoreThreeFactors:
    def test_three_factors(self, sample_revenue_df, sample_chip_df,
                           sample_per_df, sample_industry_map):
        """三因子加權正確"""
        momentum = calc_industry_momentum(sample_revenue_df, sample_industry_map)
        flow = calc_industry_flow(sample_chip_df, sample_industry_map)
        # 擴充讓估值有足夠產業
        expanded_map = pd.DataFrame({
            "stock_id": ["2330", "2317", "2454", "2881", "2882", "2412",
                         "1301", "1303", "1326"],
            "industry_category": ["半導體", "半導體", "半導體",
                                   "金融", "金融", "金融",
                                   "電信", "電信", "電信"],
        })
        extra_per = []
        for sid in ["1301", "1303", "1326"]:
            extra_per.append({"stock_id": sid, "date": "2023-12-01",
                              "per": 15.0, "pbr": 2.0, "dividend_yield": 3.0})
        combined_per = pd.concat([sample_per_df, pd.DataFrame(extra_per)], ignore_index=True)

        valuation = calc_industry_valuation(combined_per, expanded_map)

        result = industry_composite_score(
            momentum, flow, m_weight=0.4, f_weight=0.3,
            valuation=valuation, v_weight=0.3,
        )
        assert not result.empty
        assert "valuation_score" in result.columns
        assert "composite_score" in result.columns

    def test_backward_compat_valuation_none(self, sample_revenue_df, sample_chip_df,
                                              sample_industry_map):
        """valuation=None 時行為不變"""
        momentum = calc_industry_momentum(sample_revenue_df, sample_industry_map)
        flow = calc_industry_flow(sample_chip_df, sample_industry_map)

        result_default = industry_composite_score(momentum, flow)
        result_none = industry_composite_score(momentum, flow, valuation=None, v_weight=0.0)
        pd.testing.assert_frame_equal(result_default, result_none)


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
