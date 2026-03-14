"""同業比較分析工具測試"""

import numpy as np
import pandas as pd
import pytest

from analysis.utils.peer_comparison import (
    calc_peer_metrics,
    calc_peer_percentile,
    get_peers,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def industry_map():
    return pd.DataFrame({
        "stock_id": ["2330", "2303", "2454", "3711", "2317", "2382", "3008"],
        "sector": ["半導體業", "半導體業", "半導體業", "半導體業",
                    "電子零組件業", "電子零組件業", "電子零組件業"],
        "sub_industry": ["晶圓代工", "晶圓代工", "IC 設計", "IC 設計",
                         "連接器", "連接器", "被動元件"],
        "industry_category": ["半導體業", "半導體業", "半導體業", "半導體業",
                              "電子零組件業", "電子零組件業", "電子零組件業"],
    })


@pytest.fixture
def per_df():
    return pd.DataFrame({
        "stock_id": ["2330", "2303", "2454", "3711", "2317"],
        "per": [20.5, 35.2, 18.7, 45.0, 12.3],
        "pbr": [5.5, 2.1, 4.2, 3.8, 1.5],
        "dividend_yield": [2.0, 1.5, 3.5, 0.8, 5.2],
    })


@pytest.fixture
def revenue_df():
    return pd.DataFrame({
        "stock_id": ["2330", "2303", "2454", "3711", "2317"],
        "month_revenue_year_on_year": [25.3, -5.2, 40.1, 15.0, 8.5],
    })


@pytest.fixture
def price_df():
    return pd.DataFrame({
        "stock_id": ["2330", "2303", "2454", "3711", "2317"],
        "close": [800.0, 35.0, 1200.0, 150.0, 100.0],
        "volume": [50000000, 3000000, 8000000, 500000, 20000000],
    })


@pytest.fixture
def inst_df():
    return pd.DataFrame({
        "stock_id": ["2330", "2303", "2454", "3711", "2317"],
        "foreign_investors_buy": [10000, 500, 3000, 200, 5000],
        "foreign_investors_sell": [5000, 800, 1000, 300, 6000],
        "investment_trust_buy": [2000, 100, 500, 50, 800],
        "investment_trust_sell": [1000, 150, 200, 80, 900],
    })


# ---------------------------------------------------------------------------
# TestGetPeers
# ---------------------------------------------------------------------------

class TestGetPeers:
    def test_sub_industry_level(self, industry_map):
        peers = get_peers("2330", industry_map, level="sub_industry")
        assert set(peers) == {"2330", "2303"}

    def test_sector_level(self, industry_map):
        peers = get_peers("2330", industry_map, level="sector")
        assert set(peers) == {"2330", "2303", "2454", "3711"}

    def test_unknown_stock(self, industry_map):
        peers = get_peers("9999", industry_map, level="sub_industry")
        assert peers == ["9999"]

    def test_empty_map(self):
        empty = pd.DataFrame(columns=["stock_id", "sector", "sub_industry"])
        peers = get_peers("2330", empty)
        assert peers == ["2330"]

    def test_fallback_to_sector(self, industry_map):
        """sub_industry 為 None 時 fallback 到 sector"""
        map_no_sub = industry_map.copy()
        map_no_sub["sub_industry"] = None
        peers = get_peers("2330", map_no_sub, level="sub_industry")
        assert set(peers) == {"2330", "2303", "2454", "3711"}

    def test_sector_for_components(self, industry_map):
        peers = get_peers("2317", industry_map, level="sector")
        assert set(peers) == {"2317", "2382", "3008"}


# ---------------------------------------------------------------------------
# TestCalcPeerMetrics
# ---------------------------------------------------------------------------

class TestCalcPeerMetrics:
    def test_basic(self, per_df, revenue_df, price_df, inst_df):
        peers = ["2330", "2303"]
        metrics = calc_peer_metrics(
            "2330", peers,
            per_df=per_df, revenue_df=revenue_df,
            price_df=price_df, inst_df=inst_df,
        )
        assert len(metrics) == 2
        assert "is_target" in metrics.columns
        assert bool(metrics[metrics["stock_id"] == "2330"]["is_target"].iloc[0]) is True
        assert bool(metrics[metrics["stock_id"] == "2303"]["is_target"].iloc[0]) is False
        assert "close" in metrics.columns
        assert "per" in metrics.columns
        assert "inst_net_buy" in metrics.columns

    def test_with_names(self, per_df, revenue_df, price_df, inst_df):
        names = pd.DataFrame({
            "stock_id": ["2330", "2303"],
            "name": ["台積電", "聯電"],
        })
        metrics = calc_peer_metrics(
            "2330", ["2330", "2303"],
            per_df=per_df, revenue_df=revenue_df,
            price_df=price_df, inst_df=inst_df,
            stock_names=names,
        )
        assert metrics[metrics["stock_id"] == "2330"]["name"].iloc[0] == "台積電"

    def test_empty_inputs(self):
        empty = pd.DataFrame()
        metrics = calc_peer_metrics(
            "2330", ["2330"],
            per_df=empty, revenue_df=empty,
            price_df=empty, inst_df=empty,
        )
        assert len(metrics) == 1
        assert metrics["stock_id"].iloc[0] == "2330"

    def test_numeric_conversion(self, per_df, revenue_df, price_df, inst_df):
        metrics = calc_peer_metrics(
            "2330", ["2330", "2303"],
            per_df=per_df, revenue_df=revenue_df,
            price_df=price_df, inst_df=inst_df,
        )
        assert metrics["per"].dtype in [np.float64, float]


# ---------------------------------------------------------------------------
# TestCalcPeerPercentile
# ---------------------------------------------------------------------------

class TestCalcPeerPercentile:
    def test_basic(self, per_df, revenue_df, price_df, inst_df):
        peers = ["2330", "2303", "2454", "3711"]
        metrics = calc_peer_metrics(
            "2330", peers,
            per_df=per_df, revenue_df=revenue_df,
            price_df=price_df, inst_df=inst_df,
        )
        pct = calc_peer_percentile("2330", metrics)
        assert "per_pct" in pct
        assert "peer_count" in pct
        assert pct["peer_count"] == 4
        assert 0 <= pct["per_pct"] <= 100

    def test_unknown_stock(self, per_df, revenue_df, price_df, inst_df):
        metrics = calc_peer_metrics(
            "9999", ["2330", "2303"],
            per_df=per_df, revenue_df=revenue_df,
            price_df=price_df, inst_df=inst_df,
        )
        pct = calc_peer_percentile("9999", metrics)
        # 9999 不在 metrics 中的 per 等欄位，所以不會有百分位
        assert isinstance(pct, dict)

    def test_single_stock(self, per_df, revenue_df, price_df, inst_df):
        metrics = calc_peer_metrics(
            "2330", ["2330"],
            per_df=per_df, revenue_df=revenue_df,
            price_df=price_df, inst_df=inst_df,
        )
        pct = calc_peer_percentile("2330", metrics)
        # 只有一支股票時，百分位 = 100（自己就是最大/最小的）
        if "per_pct" in pct:
            assert pct["per_pct"] == 100.0

    def test_highest_value_is_100(self, per_df, revenue_df, price_df, inst_df):
        """PER 最高的股票 → PER 百分位 = 100%"""
        peers = ["2330", "2303", "2454", "3711"]
        metrics = calc_peer_metrics(
            "3711", peers,  # 3711 PER=45，最高
            per_df=per_df, revenue_df=revenue_df,
            price_df=price_df, inst_df=inst_df,
        )
        pct = calc_peer_percentile("3711", metrics)
        assert pct["per_pct"] == 100.0
