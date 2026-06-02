"""持倉追蹤測試 — 不依賴 DB，mock 資料層"""

import pandas as pd
import pytest
from unittest.mock import patch

from analysis.utils.exit_rules import (
    CompositeExit,
    PriceStopExit,
    SelectionConfig,
    StrategyVoteExit,
    TimeStopExit,
)
from analysis.utils.indicators import add_atr
import scripts.position_tracker as pt


def _picks():
    return pd.DataFrame({
        "stock_id": ["2330", "2317", "2454", "1101"],
        "stock_name": ["台積電", "鴻海", "聯發科", "台泥"],
        "rank": [1, 2, 3, 4],
        "agree_count": [4, 3, 2, 1],
        "total_score": [5.0, 6.0, 3.0, 1.0],
        "entry_price": [900.0, 200.0, 1300.0, 40.0],
        "git_commit": ["abc"] * 4,
        "app_version": ["1.1.2"] * 4,
    })


def _path(closes, start="2024-01-01"):
    dates = pd.bdate_range(start, periods=len(closes))
    df = pd.DataFrame({
        "date": dates,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
    })
    return add_atr(df)


class TestSelectToBuy:
    def test_min_agree_and_topk_equal(self):
        sel = SelectionConfig(top_k=2, weighting="equal", min_agree=2)
        out = pt._select_to_buy(_picks(), sel)
        # agree>=2 → 2330/2317/2454；rank 排序取前 2 → 2330,2317
        assert list(out["stock_id"]) == ["2330", "2317"]

    def test_weighting_score(self):
        sel = SelectionConfig(top_k=2, weighting="score", min_agree=2)
        out = pt._select_to_buy(_picks(), sel)
        # 依 total_score 排序 → 2317(6.0), 2330(5.0)
        assert list(out["stock_id"]) == ["2317", "2330"]

    def test_high_min_agree_filters_all(self):
        sel = SelectionConfig(top_k=5, weighting="equal", min_agree=9)
        assert pt._select_to_buy(_picks(), sel).empty

    def test_empty_input(self):
        assert pt._select_to_buy(pd.DataFrame(), SelectionConfig()).empty


class TestRuleUsesVotes:
    def test_vote_rule(self):
        assert pt._rule_uses_votes(StrategyVoteExit(k=2)) is True

    def test_composite_with_vote(self):
        rule = CompositeExit(rules=(TimeStopExit(20), StrategyVoteExit(2)))
        assert pt._rule_uses_votes(rule) is True

    def test_no_vote(self):
        rule = CompositeExit(rules=(TimeStopExit(20), PriceStopExit(stop_loss_pct=0.08)))
        assert pt._rule_uses_votes(rule) is False


class TestEvaluatePosition:
    def _pos(self):
        return pd.Series({
            "stock_id": "2330", "entry_price": 100.0,
            "entry_date": pd.Timestamp("2024-01-01"),
        })

    def test_time_stop(self):
        with patch.object(pt, "_price_path", return_value=_path([100.0] * 12)):
            res = pt._evaluate_position(self._pos(), TimeStopExit(max_hold_days=3), 0)
        assert res["status"] == "closed"
        assert res["exit_reason"] == "time_stop"
        assert res["holding_days"] == 3

    def test_stop_loss(self):
        # 進場 100，第 3 個交易日跌到 88（-12%）
        closes = [100.0, 100.0, 88.0] + [88.0] * 5
        with patch.object(pt, "_price_path", return_value=_path(closes)):
            res = pt._evaluate_position(self._pos(), PriceStopExit(stop_loss_pct=0.08), 0)
        assert res["status"] == "closed"
        assert res["exit_reason"] == "stop_loss"
        assert res["realized_pnl_pct"] < 0

    def test_still_open(self):
        with patch.object(pt, "_price_path", return_value=_path([100.0, 101.0, 102.0])):
            res = pt._evaluate_position(self._pos(), TimeStopExit(max_hold_days=99), 0)
        assert res["status"] == "open"
        assert res["holding_days"] == 2          # entry 後 2 個交易日
        assert res["peak_price"] == pytest.approx(102.0)

    def test_no_price_data(self):
        with patch.object(pt, "_price_path", return_value=pd.DataFrame()):
            assert pt._evaluate_position(self._pos(), TimeStopExit(3), 0) is None


class TestRunTracking:
    @patch.object(pt, "_existing_position_ids", return_value=set())
    @patch.object(pt, "save_to_db", return_value=True)
    @patch.object(pt, "_load_picks")
    @patch.object(pt, "_load_open_positions", return_value=pd.DataFrame())
    @patch.object(pt, "_ensure_table")
    @patch.object(pt, "get_engine")
    def test_opens_new_positions(self, m_eng, m_ddl, m_open, m_picks, m_save, m_exist):
        m_picks.return_value = _picks()
        sel = SelectionConfig(top_k=2, weighting="equal", min_agree=2)
        summary = pt.run_position_tracking(
            target_date="2026-05-28", selection=sel,
            exit_rule=TimeStopExit(20),
        )
        assert summary["opened"] == 2
        assert summary["closed"] == 0
        assert summary["open_count"] == 2
        # save_to_db 應被呼叫寫入新倉
        assert m_save.called

    @patch.object(pt, "_existing_position_ids", return_value=set())
    @patch.object(pt, "save_to_db", return_value=True)
    @patch.object(pt, "_apply_update")
    @patch.object(pt, "_load_picks", return_value=pd.DataFrame())
    @patch.object(pt, "_ensure_table")
    @patch.object(pt, "get_engine")
    @patch.object(pt, "_load_open_positions")
    def test_closes_on_stop_loss(self, m_open, m_eng, m_ddl, m_picks, m_apply, m_save, m_exist):
        m_open.return_value = pd.DataFrame([{
            "report_date": "2026-05-01", "stock_id": "2330",
            "stock_name": "台積電", "entry_price": 100.0,
            "entry_date": pd.Timestamp("2026-05-01"),
        }])
        closes = [100.0, 100.0, 85.0, 85.0]
        with patch.object(pt, "_price_path", return_value=_path(closes, start="2026-05-01")):
            summary = pt.run_position_tracking(
                target_date="2026-05-28",
                exit_rule=PriceStopExit(stop_loss_pct=0.08),
            )
        assert summary["closed"] == 1
        assert summary["exits"][0]["exit_reason"] == "stop_loss"
        assert m_apply.called

    @patch.object(pt, "_existing_position_ids", return_value=set())
    @patch.object(pt, "save_to_db", return_value=True)
    @patch.object(pt, "_load_picks")
    @patch.object(pt, "_load_open_positions")
    @patch.object(pt, "_ensure_table")
    @patch.object(pt, "get_engine")
    def test_skips_already_open(self, m_eng, m_ddl, m_open, m_picks, m_save, m_exist):
        """已持有的股票不重複開倉（冪等核心）。"""
        m_open.return_value = pd.DataFrame([{
            "report_date": "2026-05-01", "stock_id": "2330",
            "stock_name": "台積電", "entry_price": 100.0,
            "entry_date": pd.Timestamp("2026-05-01"),
        }])
        m_picks.return_value = _picks()  # 含 2330
        sel = SelectionConfig(top_k=2, weighting="equal", min_agree=2)
        # 2330 已持有且仍 open（時間停損不觸發）→ 只開 2317
        with patch.object(pt, "_price_path", return_value=_path([100.0, 101.0])):
            summary = pt.run_position_tracking(
                target_date="2026-05-28", selection=sel,
                exit_rule=TimeStopExit(99),
            )
        assert summary["opened"] == 1  # 只有 2317

    @patch.object(pt, "_existing_position_ids", return_value={"2330", "2317"})
    @patch.object(pt, "save_to_db", return_value=True)
    @patch.object(pt, "_load_picks")
    @patch.object(pt, "_load_open_positions", return_value=pd.DataFrame())
    @patch.object(pt, "_ensure_table")
    @patch.object(pt, "get_engine")
    def test_excludes_same_date_existing(self, m_eng, m_ddl, m_open, m_picks, m_save, m_exist):
        """同一 report_date 已存在的標的不重複開倉（含已平倉）。"""
        m_picks.return_value = _picks()  # 2330/2317 agree>=2
        sel = SelectionConfig(top_k=2, weighting="equal", min_agree=2)
        summary = pt.run_position_tracking(
            target_date="2026-05-28", selection=sel, exit_rule=TimeStopExit(20),
        )
        assert summary["opened"] == 0  # 2330/2317 皆已存在 → 不重開


def test_format_section_with_exit():
    summary = {
        "report_date": "2026-05-28", "opened": 2, "closed": 1, "open_count": 5,
        "exits": [{
            "stock_id": "2330", "stock_name": "台積電", "entry_date": "2026-05-01",
            "exit_date": "2026-05-15", "exit_price": 92.0, "exit_reason": "stop_loss",
            "realized_pnl_pct": -8.0, "holding_days": 10,
        }],
    }
    out = pt.format_tracking_section(summary)
    assert "出場訊號" in out and "stop_loss" in out and "2330" in out


def test_format_section_empty():
    assert pt.format_tracking_section({"report_date": None}) == ""
