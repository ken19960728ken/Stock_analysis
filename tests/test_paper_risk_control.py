"""
Paper Trading 風控模組測試
"""

import numpy as np
import pandas as pd
import pytest

from scripts.paper_risk_control import (
    RiskLimits,
    RiskState,
    check_risk_constraints,
    generate_halve_orders,
    generate_liquidate_orders,
    update_drawdown,
    update_strategy_losses,
)


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def risk_limits():
    return RiskLimits()


@pytest.fixture
def risk_state():
    return RiskState(peak_equity=10_000_000)


@pytest.fixture
def sample_holdings():
    return pd.DataFrame([
        {"stock_id": "2330", "shares": 5000, "entry_price": 600, "current_price": 620,
         "strategy_name": "RSI 反轉"},
        {"stock_id": "2317", "shares": 10000, "entry_price": 100, "current_price": 105,
         "strategy_name": "MA 交叉"},
    ])


@pytest.fixture
def sample_order():
    return {
        "stock_id": "2454",
        "shares": 3000,
        "price": 500.0,
        "strategy_name": "RSI 反轉",
    }


# ===================================================================
# RiskState 序列化
# ===================================================================

class TestRiskStateSerialization:

    def test_to_dict_roundtrip(self):
        state = RiskState(
            peak_equity=10_000_000,
            current_drawdown=-0.05,
            is_paused=True,
            strategy_loss_counts={"RSI 反轉": 3},
            paused_strategies={"MA 交叉"},
        )
        d = state.to_dict()
        restored = RiskState.from_dict(d)
        assert restored.peak_equity == 10_000_000
        assert restored.current_drawdown == -0.05
        assert restored.is_paused is True
        assert restored.strategy_loss_counts == {"RSI 反轉": 3}
        assert restored.paused_strategies == {"MA 交叉"}

    def test_from_db_row(self):
        row = pd.Series({
            "peak_equity": 10_000_000,
            "drawdown_pct": -0.08,
            "risk_status": "paused",
            "paused_strategies": '["MA 交叉"]',
            "strategy_loss_counts": '{"RSI 反轉": 5}',
        })
        state = RiskState.from_db_row(row)
        assert state.is_paused is True
        assert state.paused_strategies == {"MA 交叉"}
        assert state.strategy_loss_counts["RSI 反轉"] == 5

    def test_risk_status_label(self):
        state = RiskState()
        assert state.risk_status_label == "normal"
        state.is_paused = True
        assert state.risk_status_label == "paused"
        state.is_halved = True
        assert state.risk_status_label == "halved"
        state.is_liquidated = True
        assert state.risk_status_label == "liquidated"


# ===================================================================
# check_risk_constraints
# ===================================================================

class TestCheckRiskConstraints:

    def test_pass_normal(self, sample_order, sample_holdings, risk_state, risk_limits):
        allowed, reason = check_risk_constraints(
            order=sample_order,
            holdings=sample_holdings,
            cash=5_000_000,
            total_equity=10_000_000,
            risk_state=risk_state,
            risk_limits=risk_limits,
        )
        assert allowed is True

    def test_reject_drawdown_paused(self, sample_order, sample_holdings, risk_limits):
        state = RiskState(peak_equity=10_000_000, is_paused=True, current_drawdown=-0.12)
        allowed, reason = check_risk_constraints(
            order=sample_order,
            holdings=sample_holdings,
            cash=5_000_000,
            total_equity=8_800_000,
            risk_state=state,
            risk_limits=risk_limits,
        )
        assert allowed is False
        assert "暫停新建倉" in reason

    def test_reject_liquidated(self, sample_order, sample_holdings, risk_limits):
        state = RiskState(
            peak_equity=10_000_000, is_paused=True,
            is_halved=True, is_liquidated=True,
        )
        allowed, reason = check_risk_constraints(
            order=sample_order,
            holdings=sample_holdings,
            cash=5_000_000,
            total_equity=7_000_000,
            risk_state=state,
            risk_limits=risk_limits,
        )
        assert allowed is False
        assert "清倉" in reason

    def test_reject_strategy_paused(self, sample_order, sample_holdings, risk_limits):
        state = RiskState(
            peak_equity=10_000_000,
            paused_strategies={"RSI 反轉"},
            strategy_loss_counts={"RSI 反轉": 5},
        )
        allowed, reason = check_risk_constraints(
            order=sample_order,
            holdings=sample_holdings,
            cash=5_000_000,
            total_equity=10_000_000,
            risk_state=state,
            risk_limits=risk_limits,
        )
        assert allowed is False
        assert "已暫停" in reason

    def test_reject_max_positions(self, sample_order, risk_state, risk_limits):
        # 建立 10 檔持倉
        holdings = pd.DataFrame([
            {"stock_id": str(i), "shares": 1000} for i in range(10)
        ])
        allowed, reason = check_risk_constraints(
            order=sample_order,
            holdings=holdings,
            cash=5_000_000,
            total_equity=10_000_000,
            risk_state=risk_state,
            risk_limits=risk_limits,
        )
        assert allowed is False
        assert "上限" in reason

    def test_reject_cash_insufficient(self, sample_holdings, risk_state, risk_limits):
        order = {"stock_id": "2454", "shares": 10000, "price": 500, "strategy_name": "test"}
        allowed, reason = check_risk_constraints(
            order=order,
            holdings=sample_holdings,
            cash=100_000,  # 不夠
            total_equity=10_000_000,
            risk_state=risk_state,
            risk_limits=risk_limits,
        )
        assert allowed is False
        assert "現金不足" in reason

    def test_reject_single_position_too_large(self, sample_holdings, risk_state, risk_limits):
        # 單檔超過 20%
        order = {"stock_id": "2454", "shares": 5000, "price": 500, "strategy_name": "test"}
        allowed, reason = check_risk_constraints(
            order=order,
            holdings=sample_holdings,
            cash=5_000_000,
            total_equity=10_000_000,
            risk_state=risk_state,
            risk_limits=risk_limits,
        )
        # 5000 * 500 = 2,500,000 / 10,000,000 = 25% > 20%
        assert allowed is False
        assert "單檔比重" in reason

    def test_pass_single_position_within_limit(self, sample_holdings, risk_state, risk_limits):
        order = {"stock_id": "2454", "shares": 3000, "price": 500, "strategy_name": "test"}
        allowed, _ = check_risk_constraints(
            order=order,
            holdings=sample_holdings,
            cash=5_000_000,
            total_equity=10_000_000,
            risk_state=risk_state,
            risk_limits=risk_limits,
        )
        # 3000 * 500 = 1,500,000 / 10,000,000 = 15% < 20%
        assert allowed is True


# ===================================================================
# update_drawdown
# ===================================================================

class TestUpdateDrawdown:

    def test_new_high_resets(self, risk_limits):
        state = RiskState(peak_equity=9_000_000, is_paused=True)
        alerts = update_drawdown(10_000_000, state, risk_limits)
        assert state.peak_equity == 10_000_000
        assert state.is_paused is False
        assert any(a["type"] == "drawdown_reset" for a in alerts)

    def test_pause_at_10pct(self, risk_limits):
        state = RiskState(peak_equity=10_000_000)
        alerts = update_drawdown(8_900_000, state, risk_limits)
        assert state.is_paused is True
        assert state.current_drawdown == pytest.approx(-0.11, abs=0.01)
        assert any(a["type"] == "drawdown_pause" for a in alerts)

    def test_halve_at_15pct(self, risk_limits):
        state = RiskState(peak_equity=10_000_000)
        alerts = update_drawdown(8_400_000, state, risk_limits)
        assert state.is_halved is True
        assert state.is_paused is True

    def test_liquidate_at_20pct(self, risk_limits):
        state = RiskState(peak_equity=10_000_000)
        alerts = update_drawdown(7_900_000, state, risk_limits)
        assert state.is_liquidated is True
        assert state.is_halved is True
        assert any(a["severity"] == "critical" for a in alerts)

    def test_no_double_trigger(self, risk_limits):
        state = RiskState(peak_equity=10_000_000, is_paused=True)
        alerts = update_drawdown(8_500_000, state, risk_limits)
        # 已經 paused，不應再觸發 pause alert
        assert not any(a["type"] == "drawdown_pause" for a in alerts)


# ===================================================================
# update_strategy_losses
# ===================================================================

class TestUpdateStrategyLosses:

    def test_consecutive_losses_trigger_pause(self, risk_limits):
        state = RiskState(strategy_loss_counts={"RSI 反轉": 4})
        trades = [{"side": "sell", "strategy_name": "RSI 反轉", "realized_pnl": -5000}]
        alerts = update_strategy_losses(trades, state, risk_limits)
        assert "RSI 反轉" in state.paused_strategies
        assert state.strategy_loss_counts["RSI 反轉"] == 5
        assert any(a["type"] == "strategy_pause" for a in alerts)

    def test_win_resets_count(self, risk_limits):
        state = RiskState(
            strategy_loss_counts={"RSI 反轉": 4},
            paused_strategies={"RSI 反轉"},
        )
        trades = [{"side": "sell", "strategy_name": "RSI 反轉", "realized_pnl": 5000}]
        alerts = update_strategy_losses(trades, state, risk_limits)
        assert state.strategy_loss_counts["RSI 反轉"] == 0
        assert "RSI 反轉" not in state.paused_strategies
        assert any(a["type"] == "strategy_resume" for a in alerts)

    def test_buy_trades_ignored(self, risk_limits):
        state = RiskState()
        trades = [{"side": "buy", "strategy_name": "RSI 反轉", "realized_pnl": 0}]
        alerts = update_strategy_losses(trades, state, risk_limits)
        assert len(alerts) == 0
        assert state.strategy_loss_counts == {}

    def test_multiple_strategies(self, risk_limits):
        state = RiskState(strategy_loss_counts={"A": 4, "B": 0})
        trades = [
            {"side": "sell", "strategy_name": "A", "realized_pnl": -100},
            {"side": "sell", "strategy_name": "B", "realized_pnl": -200},
        ]
        alerts = update_strategy_losses(trades, state, risk_limits)
        assert state.strategy_loss_counts["A"] == 5
        assert "A" in state.paused_strategies
        assert state.strategy_loss_counts["B"] == 1
        assert "B" not in state.paused_strategies


# ===================================================================
# 熔斷訂單生成
# ===================================================================

class TestCircuitBreakerOrders:

    def test_halve_orders(self, sample_holdings):
        orders = generate_halve_orders(sample_holdings)
        assert len(orders) == 2
        # 2330: 5000 股 → 減半 = 2000 (2000 = 5000//2//1000*1000)
        order_2330 = next(o for o in orders if o["stock_id"] == "2330")
        assert order_2330["shares"] == 2000
        assert order_2330["reason"] == "risk_halve"
        # 2317: 10000 股 → 減半 = 5000
        order_2317 = next(o for o in orders if o["stock_id"] == "2317")
        assert order_2317["shares"] == 5000

    def test_halve_small_position(self):
        """不足 2 張的持倉全部賣出"""
        holdings = pd.DataFrame([
            {"stock_id": "9999", "shares": 1000, "current_price": 50, "strategy_name": "test"},
        ])
        orders = generate_halve_orders(holdings)
        assert orders[0]["shares"] == 1000  # 全賣

    def test_liquidate_orders(self, sample_holdings):
        orders = generate_liquidate_orders(sample_holdings)
        assert len(orders) == 2
        for o in orders:
            assert o["reason"] == "risk_liquidate"
        shares = {o["stock_id"]: o["shares"] for o in orders}
        assert shares["2330"] == 5000
        assert shares["2317"] == 10000
