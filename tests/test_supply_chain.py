"""供應鏈分析工具測試"""

import numpy as np
import pandas as pd
import pytest

from analysis.utils.supply_chain import (
    SUPPLY_CHAIN,
    calc_chain_lead_lag,
    calc_chain_momentum,
    get_chain_names,
    get_chain_stages,
)


@pytest.fixture
def industry_map():
    return pd.DataFrame({
        "stock_id": [
            "2330", "2303",  # 晶圓代工
            "2454", "3711",  # IC 設計
            "2325", "6239",  # IC 封測
        ],
        "sector": ["半導體業"] * 6,
        "sub_industry": [
            "晶圓代工", "晶圓代工",
            "IC 設計", "IC 設計",
            "IC 封測", "IC 封測",
        ],
    })


@pytest.fixture
def revenue_df():
    """模擬 12 個月營收資料"""
    records = []
    np.random.seed(42)
    stocks = ["2330", "2303", "2454", "3711", "2325", "6239"]
    for sid in stocks:
        for month_offset in range(12):
            date = pd.Timestamp("2025-01-01") + pd.DateOffset(months=month_offset)
            yoy = np.random.uniform(-10, 40)
            records.append({
                "stock_id": sid,
                "date": date,
                "revenue": np.random.uniform(1e8, 1e10),
                "month_revenue_year_on_year": yoy,
            })
    return pd.DataFrame(records)


class TestSupplyChainConstants:
    def test_chain_names(self):
        names = get_chain_names()
        assert len(names) >= 4
        assert "半導體供應鏈" in names
        assert "電子組裝供應鏈" in names

    def test_chain_stages(self):
        stages = get_chain_stages("半導體供應鏈")
        assert "IC 設計" in stages
        assert "晶圓代工" in stages
        assert stages.index("IC 設計") < stages.index("IC 封測")

    def test_unknown_chain(self):
        stages = get_chain_stages("不存在的供應鏈")
        assert stages == []


class TestCalcChainMomentum:
    def test_basic(self, revenue_df, industry_map):
        result = calc_chain_momentum("半導體供應鏈", revenue_df, industry_map)
        assert not result.empty
        assert "sub_industry" in result.columns
        assert "avg_yoy" in result.columns
        assert "chain_order" in result.columns

    def test_order_is_correct(self, revenue_df, industry_map):
        result = calc_chain_momentum("半導體供應鏈", revenue_df, industry_map)
        if len(result) > 1:
            # chain_order 應遞增
            orders = result["chain_order"].tolist()
            assert orders == sorted(orders)

    def test_unknown_chain(self, revenue_df, industry_map):
        result = calc_chain_momentum("不存在的", revenue_df, industry_map)
        assert result.empty

    def test_empty_revenue(self, industry_map):
        result = calc_chain_momentum("半導體供應鏈", pd.DataFrame(), industry_map)
        assert result.empty

    def test_empty_industry_map(self, revenue_df):
        result = calc_chain_momentum("半導體供應鏈", revenue_df, pd.DataFrame())
        assert result.empty

    def test_lookback_months(self, revenue_df, industry_map):
        result_3m = calc_chain_momentum("半導體供應鏈", revenue_df, industry_map, lookback_months=3)
        result_12m = calc_chain_momentum("半導體供應鏈", revenue_df, industry_map, lookback_months=12)
        # 12 個月的結果應該 stock_count 相同或更多
        if not result_3m.empty and not result_12m.empty:
            assert result_12m["stock_count"].sum() >= result_3m["stock_count"].sum()

    def test_no_sub_industry_column(self, revenue_df):
        """沒有 sub_industry 欄位"""
        bad_map = pd.DataFrame({
            "stock_id": ["2330"],
            "sector": ["半導體業"],
        })
        result = calc_chain_momentum("半導體供應鏈", revenue_df, bad_map)
        assert result.empty


class TestCalcChainLeadLag:
    def test_basic(self, revenue_df, industry_map):
        result = calc_chain_lead_lag("半導體供應鏈", revenue_df, industry_map, periods=12)
        if not result.empty:
            assert result.shape[0] == result.shape[1]  # 方陣
            # 對角線應為 0
            for i in range(len(result)):
                assert result.iloc[i, i] == 0

    def test_empty_inputs(self, industry_map):
        result = calc_chain_lead_lag("半導體供應鏈", pd.DataFrame(), industry_map)
        assert result.empty

    def test_unknown_chain(self, revenue_df, industry_map):
        result = calc_chain_lead_lag("不存在的", revenue_df, industry_map)
        assert result.empty

    def test_short_periods(self, revenue_df, industry_map):
        """periods 太短可能無法計算"""
        result = calc_chain_lead_lag("半導體供應鏈", revenue_df, industry_map, periods=2)
        # 可能為空或有結果，但不應 crash
        assert isinstance(result, pd.DataFrame)
