"""出場規則回測 harness 測試 — 不依賴 DB，驗證純函式與 composite→backtester 路徑"""

import numpy as np
import pandas as pd

from analysis.strategies.base import Strategy
from analysis.utils.exit_rules import TimeStopExit
from analysis.utils.multi_stock_backtester import MultiStockBacktester
from scripts.exit_rule_backtest import (
    _PassthroughStrategy,
    _build_composite,
    _compute_stock_panel,
    build_exit_grid,
    build_selection_grid,
)


def _price_df(n=60, start_price=100.0):
    dates = pd.bdate_range("2024-01-01", periods=n)
    closes = [start_price + i * 0.1 for i in range(n)]
    return pd.DataFrame({
        "date": dates,
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": [2_000_000] * n,
        "stock_id": "TEST",
    })


class _BuyAtIdx(Strategy):
    name = "Stub"
    params: dict = {}

    def __init__(self, buy_idx):
        super().__init__()
        self.buy_idx = buy_idx

    def generate_signals(self, data):
        df = data.copy()
        df["signal"] = 0
        df.iloc[self.buy_idx, df.columns.get_loc("signal")] = 1
        return df


class TestGrids:
    def test_quick_smaller_than_full(self):
        assert len(build_exit_grid(quick=True)) < len(build_exit_grid(quick=False))

    def test_exit_labels_unique(self):
        labels = [lbl for lbl, _ in build_exit_grid(quick=False)]
        assert len(labels) == len(set(labels))

    def test_selection_grid_shapes(self):
        tk_q, w_q, ma_q = build_selection_grid(quick=True)
        tk_f, w_f, ma_f = build_selection_grid(quick=False)
        assert len(tk_q) == 1 and len(w_q) == 1 and len(ma_q) == 1
        assert len(tk_f) >= 3 and len(w_f) == 2 and len(ma_f) >= 3


class TestComputePanel:
    def test_panel_columns_and_alignment(self):
        strategies = {"sA": _BuyAtIdx(5), "sB": _BuyAtIdx(10)}
        base, sigmat = _compute_stock_panel(
            "TEST", _price_df(), strategies, {}, {}, {}, {}
        )
        assert list(sigmat.columns) == ["sA", "sB"]
        assert len(sigmat) == len(base)
        # sA 在 idx5 發出 1
        assert sigmat["sA"].iloc[5] == 1
        assert sigmat["sB"].iloc[10] == 1

    def test_short_df_returns_none(self):
        assert _compute_stock_panel("TEST", _price_df(n=10), {}, {}, {}, {}, {}) is None


class TestBuildComposite:
    def test_signal_and_scores(self):
        base = _price_df(n=5)[["date", "open", "high", "low", "close", "volume"]]
        # 兩策略，idx3 兩者都 +1 → agree=2；idx4 一者 -1
        sigmat = pd.DataFrame({
            "sA": [0, 0, 0, 1, -1],
            "sB": [0, 0, 0, 1, 0],
        })
        out = _build_composite(base, sigmat, signal_days=1, min_agree=2)
        assert out["signal"].iloc[3] == 1          # 兩策略同意
        assert out["signal"].iloc[0] == 0
        assert out["_neg_votes"].iloc[4] == 1       # sA 發 -1
        assert out["_score"].iloc[3] > 0

    def test_min_agree_gate(self):
        base = _price_df(n=3)[["date", "open", "high", "low", "close", "volume"]]
        sigmat = pd.DataFrame({"sA": [0, 1, 0], "sB": [0, 0, 0]})
        # 只有 1 策略同意 → min_agree=2 不通過
        out2 = _build_composite(base, sigmat, signal_days=1, min_agree=2)
        assert out2["signal"].iloc[1] == 0
        out1 = _build_composite(base, sigmat, signal_days=1, min_agree=1)
        assert out1["signal"].iloc[1] == 1


class TestCompositeToBacktester:
    def test_runs_with_exit_rule(self):
        """composite df 餵進 MultiStockBacktester + 出場規則應產生交易。"""
        base = _price_df(n=60)[["date", "open", "high", "low", "close", "volume"]]
        sigmat = pd.DataFrame({"sA": [0] * 60})
        sigmat.iloc[5, 0] = 1
        comp = _build_composite(base, sigmat, signal_days=1, min_agree=1)
        bt = MultiStockBacktester(
            strategy=_PassthroughStrategy(),
            max_positions=5,
            exit_rule=TimeStopExit(max_hold_days=5),
        )
        result = bt.run({"TEST": comp})
        assert result.trade_count == 1
        assert result.trades.iloc[0]["exit_reason"] == "time_stop"
