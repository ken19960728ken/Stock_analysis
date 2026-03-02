"""
tests/test_strategy_report.py — 通用策略回測報告腳本單元測試

全部 mock DB，不需要真實連線。
"""

import io
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from scripts.strategy_report import (
    STRATEGY_DATA_NEEDS,
    backtest_one,
    calc_benchmark_buyhold,
    enrich_data,
    list_strategies,
    parse_params,
    run_report,
)


# ============================================================================
# TestParseParams
# ============================================================================

class TestParseParams:
    """測試 --param key=value 解析"""

    def test_empty_returns_empty(self):
        assert parse_params(None) == {}
        assert parse_params([]) == {}

    def test_int_value(self):
        result = parse_params(["fast_period=10"])
        assert result == {"fast_period": 10}
        assert isinstance(result["fast_period"], int)

    def test_float_value(self):
        result = parse_params(["threshold=0.05"])
        assert result == {"threshold": 0.05}
        assert isinstance(result["threshold"], float)

    def test_string_value(self):
        result = parse_params(["event_type=dividend"])
        assert result == {"event_type": "dividend"}
        assert isinstance(result["event_type"], str)

    def test_multiple_params(self):
        result = parse_params(["fast_period=5", "slow_period=20", "threshold=0.02"])
        assert result == {"fast_period": 5, "slow_period": 20, "threshold": 0.02}

    def test_invalid_format_ignored(self):
        result = parse_params(["no_equals_sign", "valid=10"])
        assert result == {"valid": 10}

    def test_value_with_equals(self):
        result = parse_params(["key=a=b"])
        assert result == {"key": "a=b"}


# ============================================================================
# TestEnrichData
# ============================================================================

class TestEnrichData:
    """測試 enrich_data 資料合併邏輯"""

    def _make_daily(self, n=50):
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        np.random.seed(42)
        close = 580 + np.cumsum(np.random.randn(n) * 2)
        return pd.DataFrame({
            "date": dates,
            "stock_id": "2330",
            "open": close - 1,
            "high": close + 3,
            "low": close - 3,
            "close": close,
            "volume": np.random.randint(20_000_000, 40_000_000, n),
        })

    def test_technical_strategy_no_enrich(self):
        """技術面策略（MA 交叉）不需要合併額外資料"""
        engine = MagicMock()
        daily = self._make_daily()
        result = enrich_data(engine, daily, "2330", "MA 交叉", "2023-01-01")
        assert list(result.columns) == list(daily.columns)

    @patch("scripts.strategy_report.load_chip_institutional")
    def test_institutional_strategy_merges(self, mock_load):
        """法人跟單策略應合併 institutional_net_buy"""
        engine = MagicMock()
        daily = self._make_daily(10)

        chip_data = pd.DataFrame({
            "date": daily["date"][:5],
            "stock_id": "2330",
            "foreign_investors_buy": [100, 200, 300, 400, 500],
            "foreign_investors_sell": [50, 100, 150, 200, 250],
            "investment_trust_buy": [10, 20, 30, 40, 50],
            "investment_trust_sell": [5, 10, 15, 20, 25],
        })
        mock_load.return_value = chip_data

        result = enrich_data(engine, daily, "2330", "法人跟單", "2023-01-01")
        assert "institutional_net_buy" in result.columns

    @patch("scripts.strategy_report.load_chip_institutional")
    def test_institutional_empty_data(self, mock_load):
        """法人資料為空時不影響原始 df"""
        engine = MagicMock()
        daily = self._make_daily(10)
        mock_load.return_value = pd.DataFrame()
        result = enrich_data(engine, daily, "2330", "法人跟單", "2023-01-01")
        assert "institutional_net_buy" not in result.columns
        assert len(result) == len(daily)

    @patch("scripts.strategy_report.load_dividend_history")
    def test_event_driven_merges_dividend(self, mock_load):
        """事件驅動策略應合併 dividend 欄位"""
        engine = MagicMock()
        daily = self._make_daily(10)
        div_data = pd.DataFrame({
            "date": [daily["date"].iloc[3]],
            "stock_id": "2330",
            "cash_dividend": [10.0],
        })
        mock_load.return_value = div_data
        result = enrich_data(engine, daily, "2330", "事件驅動", "2023-01-01")
        assert "dividend" in result.columns


# ============================================================================
# TestBacktestOne
# ============================================================================

class TestBacktestOne:
    """測試 backtest_one 回測邏輯"""

    @patch("scripts.strategy_report.enrich_data")
    @patch("scripts.strategy_report.load_daily_price")
    @patch("scripts.strategy_report.load_stock_name")
    def test_insufficient_data_returns_none(self, mock_name, mock_price, mock_enrich):
        """資料不足應回傳 (None, name)"""
        engine = MagicMock()
        mock_name.return_value = "測試股"
        mock_price.return_value = pd.DataFrame({
            "date": pd.date_range("2023-01-01", periods=5, freq="B"),
            "close": [100, 101, 102, 103, 104],
        })
        from analysis.strategies.ma_cross import MACrossStrategy
        strategy = MACrossStrategy()
        result, name = backtest_one(engine, "9999", "MA 交叉", strategy, "2023-01-01")
        assert result is None
        assert name == "測試股"
        mock_enrich.assert_not_called()

    @patch("scripts.strategy_report.enrich_data")
    @patch("scripts.strategy_report.load_daily_price")
    @patch("scripts.strategy_report.load_stock_name")
    def test_empty_data_returns_none(self, mock_name, mock_price, mock_enrich):
        """空資料應回傳 (None, name)"""
        engine = MagicMock()
        mock_name.return_value = ""
        mock_price.return_value = pd.DataFrame()
        from analysis.strategies.ma_cross import MACrossStrategy
        strategy = MACrossStrategy()
        result, name = backtest_one(engine, "9999", "MA 交叉", strategy, "2023-01-01")
        assert result is None

    @patch("scripts.strategy_report.enrich_data")
    @patch("scripts.strategy_report.load_daily_price")
    @patch("scripts.strategy_report.load_stock_name")
    def test_normal_stock_returns_result(self, mock_name, mock_price, mock_enrich):
        """正常股票應回傳 BacktestResult"""
        engine = MagicMock()
        mock_name.return_value = "台積電"

        n = 100
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        np.random.seed(42)
        close = 580 + np.cumsum(np.random.randn(n) * 2)
        daily = pd.DataFrame({
            "date": dates,
            "stock_id": "2330",
            "open": close - 1,
            "high": close + 3,
            "low": close - 3,
            "close": close,
            "volume": np.random.randint(20_000_000, 40_000_000, n),
        })
        mock_price.return_value = daily
        mock_enrich.return_value = daily

        from analysis.strategies.ma_cross import MACrossStrategy
        strategy = MACrossStrategy()
        result, name = backtest_one(engine, "2330", "MA 交叉", strategy, "2023-01-01")
        assert result is not None
        assert name == "台積電"
        assert hasattr(result, "total_return")
        assert hasattr(result, "equity_curve")


# ============================================================================
# TestCalcBenchmark
# ============================================================================

class TestCalcBenchmark:
    """測試 0050 基準計算"""

    @patch("scripts.strategy_report.load_daily_price")
    def test_sufficient_data(self, mock_price):
        """有資料應回傳 dict"""
        engine = MagicMock()
        n = 100
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        mock_price.return_value = pd.DataFrame({
            "date": dates,
            "close": [130 + i * 0.1 for i in range(n)],
        })
        result = calc_benchmark_buyhold(engine, "2023-01-01")
        assert result is not None
        assert "total_return" in result
        assert "annual_return" in result
        assert "sharpe_ratio" in result
        assert "max_drawdown" in result
        assert "equity_curve" in result

    @patch("scripts.strategy_report.load_daily_price")
    def test_empty_data_returns_none(self, mock_price):
        """空資料應回傳 None"""
        engine = MagicMock()
        mock_price.return_value = pd.DataFrame()
        result = calc_benchmark_buyhold(engine, "2023-01-01")
        assert result is None

    @patch("scripts.strategy_report.load_daily_price")
    def test_single_row_returns_none(self, mock_price):
        """只有一筆資料應回傳 None"""
        engine = MagicMock()
        mock_price.return_value = pd.DataFrame({
            "date": [pd.Timestamp("2023-01-01")],
            "close": [130.0],
        })
        result = calc_benchmark_buyhold(engine, "2023-01-01")
        assert result is None


# ============================================================================
# TestListStrategies
# ============================================================================

class TestListStrategies:
    """測試策略列表輸出"""

    def test_lists_all_16_strategies(self, capsys):
        """應列出所有 18 個策略"""
        list_strategies()
        output = capsys.readouterr().out
        from analysis.strategies import STRATEGY_MAP
        for name in STRATEGY_MAP.keys():
            assert name in output
        assert "18" in output


# ============================================================================
# TestStrategyDataNeeds
# ============================================================================

class TestStrategyDataNeeds:
    """測試策略資料需求映射"""

    def test_all_non_technical_strategies_have_needs(self):
        """所有非純技術面策略都應定義在 STRATEGY_DATA_NEEDS"""
        non_technical = [
            "法人跟單", "融資融券訊號", "股權集中度",
            "財報三率", "自由現金流", "價值投資", "多因子綜合", "事件驅動",
        ]
        for name in non_technical:
            assert name in STRATEGY_DATA_NEEDS, f"{name} 未定義資料需求"

    def test_technical_strategies_not_in_needs(self):
        """純技術面策略不應在 STRATEGY_DATA_NEEDS 中"""
        technical = ["MA 交叉", "MACD 訊號", "Bollinger 突破", "RSI 反轉",
                     "Parabolic SAR", "Heikin-Ashi", "Dual Thrust"]
        for name in technical:
            assert name not in STRATEGY_DATA_NEEDS

    def test_needs_values_are_lists(self):
        """所有需求值都應是 list"""
        for name, needs in STRATEGY_DATA_NEEDS.items():
            assert isinstance(needs, list), f"{name} 需求不是 list"

    def test_ensemble_strategy_has_needs(self):
        """多策略動態組合應定義資料需求"""
        assert "多策略動態組合" in STRATEGY_DATA_NEEDS
        assert len(STRATEGY_DATA_NEEDS["多策略動態組合"]) > 0


# ============================================================================
# TestRunReport
# ============================================================================

class TestRunReport:
    """測試 run_report 整合邏輯"""

    def test_list_mode(self, capsys):
        """strategy_name=None 應列出策略"""
        run_report(strategy_name=None)
        output = capsys.readouterr().out
        assert "內建策略一覽" in output

    def test_unknown_strategy(self, capsys):
        """未知策略名稱應印出錯誤"""
        run_report(strategy_name="不存在的策略")
        output = capsys.readouterr().out
        assert "未知策略" in output

    @patch("scripts.strategy_report.calc_benchmark_buyhold")
    @patch("scripts.strategy_report.load_daily_price")
    @patch("scripts.strategy_report.load_stock_name")
    @patch("scripts.strategy_report.load_all_stock_ids")
    @patch("scripts.strategy_report.get_engine")
    def test_report_with_stocks(self, mock_engine, mock_ids, mock_name,
                                mock_price, mock_bench, capsys, tmp_path):
        """指定股票回測應正常執行"""
        mock_engine.return_value = MagicMock()
        mock_name.return_value = "台積電"
        mock_bench.return_value = None

        n = 100
        dates = pd.date_range("2023-01-01", periods=n, freq="B")
        np.random.seed(42)
        close = 580 + np.cumsum(np.random.randn(n) * 2)
        mock_price.return_value = pd.DataFrame({
            "date": dates,
            "stock_id": "2330",
            "open": close - 1,
            "high": close + 3,
            "low": close - 3,
            "close": close,
            "volume": np.random.randint(20_000_000, 40_000_000, n),
        })

        # Patch PROJECT_ROOT to use tmp_path
        with patch("scripts.strategy_report.PROJECT_ROOT", tmp_path):
            run_report(
                strategy_name="MA 交叉",
                stock_ids=["2330"],
                no_html=True,
            )
        output = capsys.readouterr().out
        assert "策略回測報告" in output
        assert "MA 交叉" in output
