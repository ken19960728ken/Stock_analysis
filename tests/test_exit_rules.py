"""出場規則單元測試 — 純量介面，逐規則驗證"""

import pytest

from analysis.utils.exit_rules import (
    CompositeExit,
    PriceStopExit,
    StrategyVoteExit,
    TimeStopExit,
    DEFAULT_EXIT_RULE,
    DEFAULT_SELECTION,
    SelectionConfig,
)


def _call(rule, **overrides):
    base = dict(
        entry_price=100.0,
        close=100.0,
        peak_price=100.0,
        holding_days=0,
        atr=None,
        neg_votes=0,
    )
    base.update(overrides)
    return rule.should_exit(**base)


class TestTimeStopExit:
    def test_fires_at_threshold(self):
        rule = TimeStopExit(max_hold_days=5)
        assert _call(rule, holding_days=5) == (True, "time_stop")

    def test_fires_beyond_threshold(self):
        rule = TimeStopExit(max_hold_days=5)
        assert _call(rule, holding_days=8)[0] is True

    def test_not_before_threshold(self):
        rule = TimeStopExit(max_hold_days=5)
        assert _call(rule, holding_days=4) == (False, "")

    def test_zero_disables(self):
        rule = TimeStopExit(max_hold_days=0)
        assert _call(rule, holding_days=999) == (False, "")


class TestPriceStopExit:
    def test_stop_loss_fires(self):
        rule = PriceStopExit(stop_loss_pct=0.08)
        assert _call(rule, close=91.0)[1] == "stop_loss"  # -9%

    def test_stop_loss_not_at_minus_seven(self):
        rule = PriceStopExit(stop_loss_pct=0.08)
        assert _call(rule, close=93.0) == (False, "")  # -7%

    def test_take_profit_fires(self):
        rule = PriceStopExit(take_profit_pct=0.15)
        assert _call(rule, close=116.0)[1] == "take_profit"  # +16%

    def test_take_profit_not_below(self):
        rule = PriceStopExit(take_profit_pct=0.15)
        assert _call(rule, close=114.0) == (False, "")

    def test_trailing_stop_fires(self):
        # peak=120, ATR=5, mult=2 → 觸發線=110；close=109 < 110 → 出場
        rule = PriceStopExit(atr_trailing_mult=2.0)
        assert _call(rule, close=109.0, peak_price=120.0, atr=5.0)[1] == "trailing_stop"

    def test_trailing_stop_holds_above_line(self):
        rule = PriceStopExit(atr_trailing_mult=2.0)
        assert _call(rule, close=111.0, peak_price=120.0, atr=5.0) == (False, "")

    def test_trailing_needs_atr(self):
        rule = PriceStopExit(atr_trailing_mult=2.0)
        assert _call(rule, close=50.0, peak_price=120.0, atr=None) == (False, "")

    def test_stop_loss_priority_over_take_profit(self):
        rule = PriceStopExit(stop_loss_pct=0.08, take_profit_pct=0.15)
        assert _call(rule, close=80.0)[1] == "stop_loss"

    def test_zero_entry_price_no_exit(self):
        rule = PriceStopExit(stop_loss_pct=0.08)
        assert _call(rule, entry_price=0.0, close=1.0) == (False, "")


class TestStrategyVoteExit:
    def test_fires_at_k(self):
        rule = StrategyVoteExit(k=2)
        assert _call(rule, neg_votes=2) == (True, "vote_exit")

    def test_not_below_k(self):
        rule = StrategyVoteExit(k=2)
        assert _call(rule, neg_votes=1) == (False, "")

    def test_k_zero_disabled(self):
        rule = StrategyVoteExit(k=0)
        assert _call(rule, neg_votes=5) == (False, "")


class TestCompositeExit:
    def test_first_rule_wins(self):
        rule = CompositeExit(rules=(
            TimeStopExit(max_hold_days=5),
            PriceStopExit(stop_loss_pct=0.08),
        ))
        # 兩條都觸發 → 回傳第一條（time_stop）
        assert _call(rule, holding_days=10, close=80.0)[1] == "time_stop"

    def test_second_rule_fires_when_first_quiet(self):
        rule = CompositeExit(rules=(
            TimeStopExit(max_hold_days=5),
            PriceStopExit(stop_loss_pct=0.08),
        ))
        assert _call(rule, holding_days=1, close=90.0)[1] == "stop_loss"

    def test_none_fires(self):
        rule = CompositeExit(rules=(
            TimeStopExit(max_hold_days=5),
            PriceStopExit(stop_loss_pct=0.08),
        ))
        assert _call(rule, holding_days=1, close=99.0) == (False, "")


class TestDefaults:
    def test_default_selection_is_frozen(self):
        with pytest.raises(Exception):
            DEFAULT_SELECTION.top_k = 99  # frozen dataclass

    def test_default_exit_rule_time_stop(self):
        # 冠軍預設 = 20 交易日時間停損，holding>=20 觸發
        fired, reason = DEFAULT_EXIT_RULE.should_exit(
            entry_price=100, close=100, peak_price=100, holding_days=20,
        )
        assert fired and reason == "time_stop"
        # 未滿 20 日不觸發
        assert DEFAULT_EXIT_RULE.should_exit(
            entry_price=100, close=100, peak_price=100, holding_days=19,
        ) == (False, "")

    def test_default_selection_champion(self):
        assert DEFAULT_SELECTION.top_k == 10
        assert DEFAULT_SELECTION.weighting == "equal"
        assert DEFAULT_SELECTION.min_agree == 3

    def test_selection_config_defaults(self):
        cfg = SelectionConfig()
        assert cfg.weighting in ("equal", "score")
        assert cfg.top_k > 0
