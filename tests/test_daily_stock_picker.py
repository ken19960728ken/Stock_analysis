"""
每日選股報告測試 — 全部 mock，不需真實 DB

覆蓋：
  - 投票機制正確性（舊版 score_stock + 新版 _score_stock_cached）
  - 流動性 + 訊號日期過濾
  - .md 報告格式正確
  - 策略權重設定完整
  - 批量載入函式正確性
"""

import os

import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock, patch

from scripts.daily_stock_picker import (
    STRATEGY_WEIGHTS,
    STRATEGY_DATA_NEEDS,
    score_stock,
    filter_and_rank,
    generate_report,
    scan_stocks,
    build_report,
    _load_all_tables,
    _build_stock_cache,
    _load_name_map,
    _enrich_from_cache,
    _score_stock_cached,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_strategies():
    """建立 mock 策略，每個策略回傳可控的 signal"""
    strategies = {}
    for name in ["RSI 反轉", "價值投資", "機器學習選股"]:
        s = MagicMock()
        s.name = name
        strategies[name] = s
    return strategies


@pytest.fixture
def sample_daily_price_df():
    """50 天測試 OHLCV"""
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=50, freq="B")
    close = 500 + np.cumsum(np.random.randn(50) * 2)
    return pd.DataFrame({
        "date": dates, "stock_id": "2330",
        "open": close - 1, "high": close + 3, "low": close - 3,
        "close": close,
        "volume": np.random.randint(5_000_000, 50_000_000, 50),
    })


def _make_price_df(stock_id="2330", periods=50, volume=10_000_000):
    """建立測試用 OHLCV DataFrame"""
    dates = pd.date_range("2023-01-01", periods=periods, freq="B")
    close = np.array([500 + i * 2.0 for i in range(periods)])
    return pd.DataFrame({
        "date": dates, "stock_id": stock_id,
        "open": close - 1, "high": close + 3, "low": close - 3,
        "close": close,
        "volume": [volume] * periods,
    })


# ============================================================================
# TestStrategyWeights
# ============================================================================

class TestStrategyWeights:
    """策略權重設定完整性"""

    def test_all_weights_positive(self):
        """所有權重 > 0"""
        for name, w in STRATEGY_WEIGHTS.items():
            assert w > 0, f"{name} 權重應為正數"

    def test_all_strategies_have_data_needs(self):
        """所有使用的策略都有資料需求定義"""
        for name in STRATEGY_WEIGHTS:
            assert name in STRATEGY_DATA_NEEDS, f"{name} 缺少 STRATEGY_DATA_NEEDS 定義"

    def test_strategy_names_in_map(self):
        """所有使用的策略名稱在 STRATEGY_MAP 中存在"""
        from analysis.strategies import STRATEGY_MAP
        for name in STRATEGY_WEIGHTS:
            assert name in STRATEGY_MAP, f"{name} 不在 STRATEGY_MAP 中"


# ============================================================================
# TestScoreStock（舊版，保留向後相容）
# ============================================================================

class TestScoreStock:
    """投票機制正確性"""

    @patch("scripts.daily_stock_picker.enrich_data")
    @patch("scripts.daily_stock_picker.load_daily_price")
    def test_basic_scoring(self, mock_load, mock_enrich, mock_engine):
        """基本評分流程"""
        df = _make_price_df("2330", 50, 10_000_000)
        mock_load.return_value = df
        mock_enrich.return_value = df.copy()

        strategies = {}
        for name in ["RSI 反轉", "價值投資"]:
            s = MagicMock()
            signal_df = df.copy()
            signal_df["signal"] = 0
            signal_df.iloc[-1, signal_df.columns.get_loc("signal")] = 1
            s.generate_signals.return_value = signal_df
            strategies[name] = s

        result = score_stock(mock_engine, "2330", strategies, "2023-01-01", 5)
        assert result is not None
        assert result["stock_id"] == "2330"
        assert result["agree_count"] == 2
        assert result["total_score"] > 0

    @patch("scripts.daily_stock_picker.load_daily_price")
    def test_low_volume_filtered(self, mock_load, mock_engine):
        """成交量太低 → 回傳 None"""
        df = _make_price_df("9999", 50, 100_000)
        df["close"] = 100
        mock_load.return_value = df
        result = score_stock(mock_engine, "9999", {}, "2023-01-01", 5)
        assert result is None

    @patch("scripts.daily_stock_picker.load_daily_price")
    def test_short_data_filtered(self, mock_load, mock_engine):
        """資料量不足 → 回傳 None"""
        df = _make_price_df("9999", 5, 10_000_000)
        mock_load.return_value = df
        result = score_stock(mock_engine, "9999", {}, "2023-01-01", 5)
        assert result is None

    @patch("scripts.daily_stock_picker.load_daily_price")
    def test_empty_data_filtered(self, mock_load, mock_engine):
        """空資料 → 回傳 None"""
        mock_load.return_value = pd.DataFrame()
        result = score_stock(mock_engine, "9999", {}, "2023-01-01", 5)
        assert result is None


# ============================================================================
# TestFilterStocks
# ============================================================================

class TestFilterStocks:
    """過濾 + 排名"""

    def test_filter_by_agree_count(self):
        """需要至少 2 個策略同意"""
        results = [
            {"stock_id": "A", "total_score": 5.0, "agree_count": 3},
            {"stock_id": "B", "total_score": 3.0, "agree_count": 1},  # 不夠
            {"stock_id": "C", "total_score": 4.0, "agree_count": 2},
        ]
        ranked = filter_and_rank(results, top_n=10, min_agree=2)
        assert len(ranked) == 2
        assert ranked[0]["stock_id"] == "A"
        assert ranked[1]["stock_id"] == "C"

    def test_filter_negative_score(self):
        """負分數被排除"""
        results = [
            {"stock_id": "A", "total_score": -1.0, "agree_count": 2},
            {"stock_id": "B", "total_score": 2.0, "agree_count": 2},
        ]
        ranked = filter_and_rank(results, top_n=10)
        assert len(ranked) == 1
        assert ranked[0]["stock_id"] == "B"

    def test_top_n_limit(self):
        """Top N 限制"""
        results = [
            {"stock_id": str(i), "total_score": float(10 - i), "agree_count": 3}
            for i in range(10)
        ]
        ranked = filter_and_rank(results, top_n=3)
        assert len(ranked) == 3

    def test_ranking_by_score(self):
        """按分數排序"""
        results = [
            {"stock_id": "A", "total_score": 2.0, "agree_count": 2},
            {"stock_id": "B", "total_score": 5.0, "agree_count": 2},
            {"stock_id": "C", "total_score": 3.0, "agree_count": 2},
        ]
        ranked = filter_and_rank(results, top_n=10)
        assert ranked[0]["stock_id"] == "B"
        assert ranked[1]["stock_id"] == "C"
        assert ranked[2]["stock_id"] == "A"

    def test_empty_results(self):
        ranked = filter_and_rank([], top_n=10)
        assert ranked == []


# ============================================================================
# TestReportGeneration
# ============================================================================

class TestReportGeneration:
    """報告格式正確性"""

    def test_basic_report_structure(self):
        """報告包含必要段落（使用 name_map）"""
        ranked = [{
            "stock_id": "2330",
            "total_score": 3.5,
            "agree_count": 3,
            "total_strategies": 3,
            "last_close": 875.0,
            "last_date": pd.Timestamp("2023-03-01"),
            "week_return": 3.2,
            "week_vol_change": 15.0,
            "rsi": 42.3,
            "avg_volume_20d": 35000,
            "votes": {
                "RSI 反轉": {"latest_signal": 1, "recent_score": 2.0, "signal_date": pd.Timestamp("2023-02-28")},
                "價值投資": {"latest_signal": 0, "recent_score": 1.0, "signal_date": None},
            },
        }]

        report = generate_report(
            ranked, strategies_used=["RSI 反轉", "價值投資"],
            total_scanned=2087, report_date="2023-03-01",
            name_map={"2330": "台積電"},
        )

        assert "# 每日選股報告" in report
        assert "## 報告摘要" in report
        assert "## 推薦清單" in report
        assert "2330" in report
        assert "台積電" in report
        assert "875.0" in report
        assert "## 風險提示" in report

    def test_empty_report(self):
        """無推薦 → 有空報告"""
        report = generate_report([], strategies_used=["RSI 反轉"],
                                 total_scanned=100, report_date="2023-03-01")
        assert "# 每日選股報告" in report
        assert "無符合條件" in report

    def test_report_markdown_format(self):
        """報告為有效 Markdown"""
        ranked = [{
            "stock_id": "2330",
            "total_score": 2.0,
            "agree_count": 2,
            "total_strategies": 2,
            "last_close": 500.0,
            "last_date": pd.Timestamp("2023-03-01"),
            "week_return": 1.0,
            "week_vol_change": 5.0,
            "rsi": 50.0,
            "avg_volume_20d": 10000,
            "votes": {
                "RSI 反轉": {"latest_signal": 1, "recent_score": 1.0, "signal_date": None},
            },
        }]

        report = generate_report(
            ranked, strategies_used=["RSI 反轉"],
            total_scanned=100, report_date="2023-03-01",
            name_map={"2330": "測試"},
        )

        # Markdown table 格式
        assert "|------|------|" in report
        # 標題格式
        assert report.startswith("#")


# ============================================================================
# TestLoadAllTables（批量載入）
# ============================================================================

class TestLoadAllTables:
    """批量載入 4 張表（分段查詢）"""

    @patch("scripts.daily_stock_picker.safe_read_sql")
    def test_loads_four_tables(self, mock_sql):
        """回傳包含 4 張表的 dict"""
        mock_sql.return_value = pd.DataFrame({"stock_id": [], "date": []})
        result = _load_all_tables("2023-01-01", "2023-03-01")
        assert set(result.keys()) == {"daily_price", "chip_institutional", "stock_per", "month_revenue"}
        # 分段查詢：每表按 45 天一段，呼叫次數 > 4
        assert mock_sql.call_count >= 4

    @patch("scripts.daily_stock_picker.safe_read_sql")
    def test_month_revenue_earlier_start(self, mock_sql):
        """month_revenue 的查詢範圍比其他表更早（需要去年同期算 YoY）"""
        mock_sql.return_value = pd.DataFrame()
        _load_all_tables("2023-06-01", "2023-09-01")
        # 找出所有查詢的最早 sd 參數
        all_sd = []
        for call in mock_sql.call_args_list:
            params = call[1].get("params", {})
            if "sd" in params:
                all_sd.append(params["sd"])
        # 至少有一個查詢的 sd 早於 2023-06-01（month_revenue 的 YoY 回溯）
        assert any(sd < "2023-06-01" for sd in all_sd), f"所有 sd: {all_sd}"


# ============================================================================
# TestBuildStockCache（分組快取）
# ============================================================================

class TestBuildStockCache:
    """分組邏輯"""

    def test_groups_by_stock_id(self):
        """依 stock_id 正確分組"""
        df = pd.DataFrame({
            "stock_id": ["2330", "2330", "2317", "2317"],
            "date": pd.date_range("2023-01-01", periods=2).tolist() * 2,
            "close": [500, 505, 100, 102],
        })
        cache = _build_stock_cache(df)
        assert set(cache.keys()) == {"2330", "2317"}
        assert len(cache["2330"]) == 2
        assert len(cache["2317"]) == 2

    def test_empty_dataframe(self):
        """空 DataFrame → 空 dict"""
        assert _build_stock_cache(pd.DataFrame()) == {}

    def test_none_input(self):
        """None → 空 dict"""
        assert _build_stock_cache(None) == {}


class TestEnrichFromCache:
    """enrich 補充資料合併（dtype regression）"""

    def test_object_date_extra_merges_without_error(self):
        """Regression: 快取補充資料 date 為 object 字串、price date 為 datetime64，
        merge_asof 不應拋 MergeError，且補充欄位要正確填入（非全 NaN）。

        舊版只轉 price date、不轉 extra date，merge_asof 拋
        `MergeError: Incompatible merge dtype`，被上層 except 靜默吞掉，
        導致依賴非價格資料的策略恆 0 分。
        """
        price = pd.DataFrame({
            "stock_id": ["2330"] * 8,
            "date": pd.date_range("2026-04-13", periods=8, freq="B"),
            "close": [900 + i for i in range(8)],
        })
        # 模擬 _build_stock_cache 的真實輸出：date 為 object 字串
        chip = pd.DataFrame({
            "stock_id": ["2330"] * 5,
            "date": ["2026-04-13", "2026-04-14", "2026-04-15",
                     "2026-04-16", "2026-04-17"],
            "foreign_investors_buy": [100, 200, 150, 300, 250],
            "foreign_investors_sell": [50, 80, 90, 100, 70],
        })
        assert chip["date"].dtype == object  # 確認重現真實情境
        chip_cache = {"2330": chip}

        result = _enrich_from_cache(
            price.copy(), "2330", "法人跟單",
            chip_cache, {}, {}, {},
        )

        # merge 成功，補充欄位存在且非全 NaN（舊版會拋 MergeError）
        assert "institutional_net_buy" in result.columns
        assert result["institutional_net_buy"].notna().any()
        assert len(result) == len(price)


# ============================================================================
# TestScoreStockCached（快取評分）
# ============================================================================

class TestScoreStockCached:
    """快取評分正確性"""

    def test_basic_scoring_from_cache(self):
        """從快取取資料 → 正常評分"""
        df = _make_price_df("2330", 50, 10_000_000)
        price_cache = {"2330": df}

        strategies = {}
        for name in ["RSI 反轉", "價值投資"]:
            s = MagicMock()
            signal_df = df.copy()
            signal_df["signal"] = 0
            signal_df.iloc[-1, signal_df.columns.get_loc("signal")] = 1
            s.generate_signals.return_value = signal_df
            strategies[name] = s

        result = _score_stock_cached("2330", strategies, 5,
                                     price_cache, {}, {}, {}, {})
        assert result is not None
        assert result["stock_id"] == "2330"
        assert result["agree_count"] == 2
        assert result["total_score"] > 0

    def test_no_price_in_cache(self):
        """快取中無此股票 → None"""
        result = _score_stock_cached("9999", {}, 5, {}, {}, {}, {}, {})
        assert result is None

    def test_low_volume_filtered(self):
        """volume < 500 張 → None"""
        df = _make_price_df("9999", 50, 100_000)  # 100 張
        df["close"] = 100
        result = _score_stock_cached("9999", {}, 5,
                                     {"9999": df}, {}, {}, {}, {})
        assert result is None

    def test_no_db_calls_during_scoring(self):
        """整個評分流程不呼叫任何 DB 函式"""
        df = _make_price_df("2330", 50, 10_000_000)
        s = MagicMock()
        signal_df = df.copy()
        signal_df["signal"] = 0
        s.generate_signals.return_value = signal_df

        with patch("scripts.daily_stock_picker.safe_read_sql") as mock_sql, \
             patch("scripts.daily_stock_picker._load_table") as mock_load:
            _score_stock_cached("2330", {"RSI 反轉": s}, 5,
                                {"2330": df}, {}, {}, {}, {})
            mock_sql.assert_not_called()
            mock_load.assert_not_called()


# ============================================================================
# TestEnrichFromCache（快取資料合併）
# ============================================================================

class TestEnrichFromCache:
    """從快取合併資料"""

    def test_chip_institutional_merge(self):
        """chip_institutional merge 正確，含 institutional_net_buy"""
        dates = pd.date_range("2023-01-01", periods=5, freq="B")
        df = pd.DataFrame({"date": dates, "close": [100] * 5, "volume": [1000] * 5})
        chip_df = pd.DataFrame({
            "date": dates, "stock_id": "2330",
            "Foreign_Investor_buy": [100, 200, 300, 400, 500],
            "Foreign_Investor_sell": [50, 100, 150, 200, 250],
        })
        chip_cache = {"2330": chip_df}
        enriched = _enrich_from_cache(df, "2330", "法人跟單", chip_cache, {}, {}, {})
        assert "institutional_net_buy" in enriched.columns
        assert len(enriched) == 5

    def test_stock_per_merge_asof(self):
        """stock_per 用 merge_asof 前向填充"""
        dates = pd.date_range("2023-01-01", periods=10, freq="B")
        df = pd.DataFrame({"date": dates, "close": [100] * 10, "volume": [1000] * 10})
        # PER 只有 2 筆月度資料
        per_df = pd.DataFrame({
            "date": [dates[0], dates[5]],
            "stock_id": ["2330", "2330"],
            "per": [15.0, 16.0],
        })
        per_cache = {"2330": per_df}
        enriched = _enrich_from_cache(df, "2330", "價值投資", {}, per_cache, {}, {})
        assert "per" in enriched.columns
        assert not enriched["per"].isna().all()

    def test_missing_stock_in_cache(self):
        """快取中無此股票 → 回傳原始 df，不報錯"""
        dates = pd.date_range("2023-01-01", periods=5, freq="B")
        df = pd.DataFrame({"date": dates, "close": [100] * 5, "volume": [1000] * 5})
        enriched = _enrich_from_cache(df, "9999", "法人跟單", {}, {}, {}, {})
        assert len(enriched) == len(df)


# ============================================================================
# TestLoadNameMap（批量名稱載入）
# ============================================================================

class TestLoadNameMap:
    """批量載入股票名稱"""

    @patch("scripts.daily_stock_picker.safe_read_sql")
    def test_returns_dict(self, mock_sql):
        """批量載入股票名稱回傳 dict"""
        mock_sql.return_value = pd.DataFrame({
            "stock_id": ["2330", "2317"],
            "name": ["台積電", "鴻海"],
        })
        name_map = _load_name_map()
        assert name_map["2330"] == "台積電"
        assert name_map.get("9999") is None


# ============================================================================
# TestScanStocksAndBuildReport（選取 / 報告分離）
# ============================================================================

class TestScanStocks:
    """scan_stocks() 回傳結構正確性"""

    @patch("scripts.daily_stock_picker.load_industry_map", return_value={})
    @patch("scripts.daily_stock_picker._load_name_map", return_value={"2330": "台積電"})
    @patch("scripts.daily_stock_picker._load_all_tables")
    @patch("scripts.daily_stock_picker.load_all_stock_ids", return_value=["2330"])
    @patch("scripts.daily_stock_picker.get_engine")
    def test_returns_expected_keys(self, mock_engine, mock_ids, mock_tables,
                                   mock_names, mock_ind):
        """scan_stocks 回傳的 dict 包含所有必要 key"""
        df = _make_price_df("2330", 50, 10_000_000)
        mock_tables.return_value = {
            "daily_price": df,
            "chip_institutional": pd.DataFrame(),
            "stock_per": pd.DataFrame(),
            "month_revenue": pd.DataFrame(),
        }
        # mock STRATEGY_MAP 避免真正跑策略
        with patch("scripts.daily_stock_picker.STRATEGY_MAP", {}), \
             patch("scripts.daily_stock_picker.STRATEGY_WEIGHTS", {}):
            result = scan_stocks(top_n=5, target_date="2023-03-01")

        assert result is not None
        expected_keys = {"ranked", "all_results", "strategies_used",
                         "total_scanned", "report_date", "ind_map", "name_map"}
        assert set(result.keys()) == expected_keys
        assert result["report_date"] == "2023-03-01"
        assert result["total_scanned"] == 1
        assert result["name_map"]["2330"] == "台積電"

    @patch("scripts.daily_stock_picker.get_engine", side_effect=Exception("DB down"))
    def test_db_failure_returns_none(self, mock_engine):
        """DB 連線失敗 → None"""
        result = scan_stocks(target_date="2023-03-01")
        assert result is None


class TestBuildReport:
    """build_report() 報告產出正確性"""

    def test_produces_report_file(self, tmp_path):
        """build_report 寫入 .md 檔案"""
        scan_result = {
            "ranked": [{
                "stock_id": "2330",
                "total_score": 3.5,
                "agree_count": 3,
                "total_strategies": 3,
                "last_close": 875.0,
                "last_date": pd.Timestamp("2023-03-01"),
                "week_return": 3.2,
                "week_vol_change": 15.0,
                "rsi": 42.3,
                "avg_volume_20d": 35000,
                "votes": {
                    "RSI 反轉": {"latest_signal": 1, "recent_score": 2.0,
                                "signal_date": pd.Timestamp("2023-02-28")},
                },
            }],
            "all_results": [],
            "strategies_used": ["RSI 反轉"],
            "total_scanned": 100,
            "report_date": "2023-03-01",
            "ind_map": {},
            "name_map": {"2330": "台積電"},
        }
        filepath = build_report(scan_result, output_dir=str(tmp_path))
        assert filepath is not None
        assert os.path.exists(filepath)
        with open(filepath) as f:
            content = f.read()
        assert "# 每日選股報告" in content
        assert "台積電" in content

    def test_empty_ranked(self, tmp_path):
        """無推薦股票仍產出報告"""
        scan_result = {
            "ranked": [],
            "all_results": [],
            "strategies_used": ["RSI 反轉"],
            "total_scanned": 100,
            "report_date": "2023-03-01",
            "ind_map": {},
            "name_map": {},
        }
        filepath = build_report(scan_result, output_dir=str(tmp_path))
        assert filepath is not None
        with open(filepath) as f:
            content = f.read()
        assert "無符合條件" in content
