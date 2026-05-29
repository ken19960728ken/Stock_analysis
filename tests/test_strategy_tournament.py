"""
策略淘汰賽測試
"""

import numpy as np
import pandas as pd
import pytest

from scripts.strategy_tournament import (
    DECAY_HORIZONS,
    OOS_SHARPE_MIN,
    DECAY_RATE_MAX,
    _build_report,
    _evaluate_strategy,
    _fmt,
    _pct,
    _should_rerun,
    get_approved_strategies,
)


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def sample_ohlcv_500d():
    """500 交易日的模擬 OHLCV 資料"""
    dates = pd.bdate_range("2023-01-01", periods=500)
    np.random.seed(42)
    close = 100 + np.cumsum(np.random.randn(500) * 0.5)
    close = np.maximum(close, 10)  # 避免負數
    return pd.DataFrame({
        "date": dates,
        "open": close * (1 + np.random.uniform(-0.01, 0.01, 500)),
        "high": close * (1 + np.random.uniform(0, 0.02, 500)),
        "low": close * (1 + np.random.uniform(-0.02, 0, 500)),
        "close": close,
        "volume": np.random.randint(500000, 5000000, 500),
    })


# ===================================================================
# 格式化工具
# ===================================================================

class TestFormatters:

    def test_fmt_normal(self):
        assert _fmt(1.234) == "1.234"

    def test_fmt_nan(self):
        assert _fmt(np.nan) == "-"

    def test_fmt_none(self):
        assert _fmt(None) == "-"

    def test_pct_normal(self):
        assert _pct(0.1234) == "12.34%"

    def test_pct_nan(self):
        assert _pct(np.nan) == "-"


# ===================================================================
# 策略評估
# ===================================================================

class TestEvaluateStrategy:

    def test_evaluate_with_mock_data(self, sample_ohlcv_500d):
        """測試對 MA 交叉策略的 OOS 評估"""
        from analysis.strategies.ma_cross import MACrossStrategy

        stock_data = {
            "TEST01": {"price": sample_ohlcv_500d},
        }
        result = _evaluate_strategy("MA 交叉", MACrossStrategy, stock_data)
        assert result["name"] == "MA 交叉"
        assert result["stock_count"] >= 0
        assert result["verdict"] in ("stable", "moderate", "severe", "overfitting", "no_data")

    def test_evaluate_insufficient_data(self):
        """資料不足時回傳 no_data"""
        short_data = pd.DataFrame({
            "date": pd.bdate_range("2024-01-01", periods=50),
            "close": range(50),
            "open": range(50),
            "high": range(50),
            "low": range(50),
            "volume": [1000000] * 50,
        })
        from analysis.strategies.ma_cross import MACrossStrategy

        result = _evaluate_strategy(
            "MA 交叉", MACrossStrategy, {"X": {"price": short_data}},
        )
        assert result["stock_count"] == 0
        assert result["verdict"] == "no_data"

    def test_evaluate_empty_stocks(self):
        from analysis.strategies.ma_cross import MACrossStrategy
        result = _evaluate_strategy("MA 交叉", MACrossStrategy, {})
        assert result["stock_count"] == 0


# ===================================================================
# 報告生成
# ===================================================================

class TestBuildReport:

    def test_report_content(self):
        results = [
            {
                "name": "A策略", "is_sharpe_avg": 1.5, "oos_sharpe_avg": 0.8,
                "decay_rate_avg": 0.3, "verdict": "moderate",
                "signal_decay_t5": 0.01, "signal_decay_t10": 0.02,
                "signal_decay_t20": 0.03, "stock_count": 10,
            },
            {
                "name": "B策略", "is_sharpe_avg": 0.5, "oos_sharpe_avg": 0.2,
                "decay_rate_avg": 0.8, "verdict": "overfitting",
                "signal_decay_t5": -0.005, "signal_decay_t10": -0.01,
                "signal_decay_t20": -0.02, "stock_count": 10,
            },
        ]
        approved = ["A策略"]
        report = _build_report(results, approved, "2026-03-27")
        assert "策略淘汰賽報告" in report
        assert "A策略" in report
        assert "B策略" in report
        assert "通過策略" in report

    def test_report_no_approved(self):
        results = [{"name": "X", "is_sharpe_avg": 0.1, "oos_sharpe_avg": 0.1,
                     "decay_rate_avg": 0.9, "verdict": "overfitting",
                     "signal_decay_t5": np.nan, "signal_decay_t10": np.nan,
                     "signal_decay_t20": np.nan, "stock_count": 5}]
        report = _build_report(results, [], "2026-03-27")
        assert "無策略通過" in report


# ===================================================================
# 快取判斷
# ===================================================================

class TestShouldRerun:

    def test_force_always_true(self, monkeypatch):
        assert _should_rerun(force=True) is True

    def test_no_db_returns_true(self, monkeypatch):
        """DB 不可用時應重新跑"""
        monkeypatch.setattr(
            "scripts.strategy_tournament.safe_read_sql",
            lambda *a, **kw: (_ for _ in ()).throw(Exception("no DB")),
        )
        assert _should_rerun(force=False) is True


# ===================================================================
# get_approved_strategies
# ===================================================================

class TestGetApprovedStrategies:

    def test_fallback_when_no_cache(self, monkeypatch):
        """無快取時使用 fallback 策略"""
        monkeypatch.setattr(
            "scripts.strategy_tournament.safe_read_sql",
            lambda *a, **kw: pd.DataFrame(),
        )
        monkeypatch.setattr(
            "scripts.strategy_tournament.run_tournament",
            lambda **kw: {"approved_strategies": []},
        )
        strategies = get_approved_strategies()
        # 應該 fallback 到預設策略
        assert len(strategies) > 0
        names = [name for name, _ in strategies]
        assert "RSI 反轉" in names
