"""
每日選股報告測試 — 全部 mock，不需真實 DB

覆蓋：
  - 投票機制正確性
  - 流動性 + 訊號日期過濾
  - .md 報告格式正確
  - 策略權重設定完整
"""

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
# TestScoreStock
# ============================================================================

class TestScoreStock:
    """投票機制正確性"""

    @patch("scripts.daily_stock_picker.enrich_data")
    @patch("scripts.daily_stock_picker.load_daily_price")
    def test_basic_scoring(self, mock_load, mock_enrich, mock_engine):
        """基本評分流程"""
        np.random.seed(42)
        dates = pd.date_range("2023-01-01", periods=50, freq="B")
        close = np.array([500 + i * 2.0 for i in range(50)])
        df = pd.DataFrame({
            "date": dates, "stock_id": "2330",
            "open": close - 1, "high": close + 3, "low": close - 3,
            "close": close,
            "volume": [10_000_000] * 50,  # 10000 張 > 500 張
        })
        mock_load.return_value = df
        mock_enrich.return_value = df.copy()

        # 建立 mock 策略：都給正訊號
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
        dates = pd.date_range("2023-01-01", periods=50, freq="B")
        df = pd.DataFrame({
            "date": dates, "stock_id": "9999",
            "open": [100] * 50, "high": [105] * 50, "low": [95] * 50,
            "close": [100] * 50,
            "volume": [100_000] * 50,  # 100 張 < 500 張
        })
        mock_load.return_value = df

        result = score_stock(mock_engine, "9999", {}, "2023-01-01", 5)
        assert result is None

    @patch("scripts.daily_stock_picker.load_daily_price")
    def test_short_data_filtered(self, mock_load, mock_engine):
        """資料量不足 → 回傳 None"""
        dates = pd.date_range("2023-01-01", periods=5, freq="B")
        df = pd.DataFrame({
            "date": dates, "stock_id": "9999",
            "open": [100] * 5, "high": [105] * 5, "low": [95] * 5,
            "close": [100] * 5, "volume": [10_000_000] * 5,
        })
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

    def test_basic_report_structure(self, mock_engine):
        """報告包含必要段落"""
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

        with patch("scripts.daily_stock_picker.load_stock_name", return_value="台積電"):
            report = generate_report(
                ranked, mock_engine, ["RSI 反轉", "價值投資"], 2087, "2023-03-01"
            )

        assert "# 每日選股報告" in report
        assert "## 報告摘要" in report
        assert "## 推薦清單" in report
        assert "2330" in report
        assert "台積電" in report
        assert "875.0" in report
        assert "## 風險提示" in report

    def test_empty_report(self, mock_engine):
        """無推薦 → 有空報告"""
        report = generate_report([], mock_engine, ["RSI 反轉"], 100, "2023-03-01")
        assert "# 每日選股報告" in report
        assert "無符合條件" in report

    def test_report_markdown_format(self, mock_engine):
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

        with patch("scripts.daily_stock_picker.load_stock_name", return_value="測試"):
            report = generate_report(ranked, mock_engine, ["RSI 反轉"], 100, "2023-03-01")

        # Markdown table 格式
        assert "|------|------|" in report
        # 標題格式
        assert report.startswith("#")
