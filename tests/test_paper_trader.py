"""
Paper Trading 引擎測試
"""

import numpy as np
import pandas as pd
import pytest

from scripts.paper_trader import (
    COMMISSION_RATE,
    LOT_SIZE,
    SELL_TAX_RATE,
    _calc_dynamic_slippage,
    _construct_orders,
    _execute_orders,
    _scan_signals,
)


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def sample_price_cache():
    """模擬 price_cache: {stock_id: DataFrame}"""
    np.random.seed(42)
    stocks = {}
    for sid in ["2330", "2317", "2454", "2412", "2882"]:
        dates = pd.bdate_range("2025-10-01", periods=60)
        close = 100 + np.cumsum(np.random.randn(60) * 0.5)
        close = np.maximum(close, 10)
        stocks[sid] = pd.DataFrame({
            "date": dates,
            "open": close * 0.99,
            "high": close * 1.01,
            "low": close * 0.98,
            "close": close,
            "volume": np.random.randint(1000000, 5000000, 60),
        })
    return stocks


@pytest.fixture
def sample_holdings():
    return pd.DataFrame([
        {"stock_id": "2330", "shares": 5000, "entry_price": 600,
         "entry_date": "2025-12-01", "current_price": 620, "strategy_name": "RSI 反轉"},
    ])


@pytest.fixture
def risk_state():
    from scripts.paper_risk_control import RiskState
    return RiskState(peak_equity=10_000_000)


@pytest.fixture
def risk_limits():
    from scripts.paper_risk_control import RiskLimits
    return RiskLimits()


# ===================================================================
# 動態滑價
# ===================================================================

class TestDynamicSlippage:

    def test_base_slippage(self):
        slippage = _calc_dynamic_slippage(1000, 0)
        assert slippage == pytest.approx(0.0005)

    def test_with_volume(self):
        slippage = _calc_dynamic_slippage(1000, 1_000_000)
        # participation = 1000/1M = 0.001
        # impact = 0.001 * 0.1 = 0.0001
        # total = 0.0005 + 0.0001 = 0.0006
        assert slippage == pytest.approx(0.0006)

    def test_high_participation(self):
        slippage = _calc_dynamic_slippage(100000, 500000)
        # participation = 0.2, impact = 0.02
        assert slippage > 0.02


# ===================================================================
# 訊號掃描
# ===================================================================

class TestScanSignals:

    def test_scan_basic(self, sample_price_cache):
        """基本掃描測試（用純技術面策略）"""
        from analysis.strategies.ma_cross import MACrossStrategy

        strategies = [("MA 交叉", MACrossStrategy)]
        results = _scan_signals(
            strategies, sample_price_cache,
            chip_cache={}, per_cache={}, rev_cache={},
        )
        # 應該掃描到一些股票
        assert isinstance(results, dict)
        for sid, sigs in results.items():
            assert "MA 交叉" in sigs
            assert sigs["MA 交叉"] in (-1, 0, 1)

    def test_scan_empty_cache(self):
        results = _scan_signals(
            [("MA 交叉", type("MockStrategy", (), {"generate_signals": lambda s, d: d}))],
            {}, {}, {}, {},
        )
        assert results == {}


# ===================================================================
# 訂單構建
# ===================================================================

class TestConstructOrders:

    def test_sell_on_negative_signal(
        self, sample_holdings, sample_price_cache, risk_state, risk_limits,
    ):
        signals = {"2330": {"RSI 反轉": -1}}
        orders = _construct_orders(
            signals, sample_holdings, 5_000_000, 10_000_000,
            sample_price_cache, risk_state, risk_limits,
        )
        sell_orders = [o for o in orders if o["side"] == "sell"]
        assert len(sell_orders) == 1
        assert sell_orders[0]["stock_id"] == "2330"

    def test_buy_new_stock(
        self, sample_holdings, sample_price_cache, risk_state, risk_limits,
    ):
        signals = {
            "2317": {"MA 交叉": 1},
            "2454": {"RSI 反轉": 1},
            "2412": {"量價動能": 1},
            "2882": {"趨勢過濾MA": 1},
        }
        # 更多候選 + 更高 equity 使單檔比重 < 20%
        orders = _construct_orders(
            signals, sample_holdings, 5_000_000, 30_000_000,
            sample_price_cache, risk_state, risk_limits,
        )
        buy_orders = [o for o in orders if o["side"] == "buy"]
        assert len(buy_orders) >= 1
        # 每筆買單都應該是整張
        for o in buy_orders:
            assert o["shares"] % LOT_SIZE == 0

    def test_no_buy_when_paused(
        self, sample_holdings, sample_price_cache, risk_limits,
    ):
        from scripts.paper_risk_control import RiskState
        paused_state = RiskState(peak_equity=10_000_000, is_paused=True)
        signals = {"2317": {"MA 交叉": 1}}
        orders = _construct_orders(
            signals, sample_holdings, 5_000_000, 10_000_000,
            sample_price_cache, paused_state, risk_limits,
        )
        buy_orders = [o for o in orders if o["side"] == "buy"]
        assert len(buy_orders) == 0

    def test_skip_held_stocks(
        self, sample_holdings, sample_price_cache, risk_state, risk_limits,
    ):
        """已持有的股票不應該再買"""
        signals = {"2330": {"RSI 反轉": 1}}
        orders = _construct_orders(
            signals, sample_holdings, 5_000_000, 10_000_000,
            sample_price_cache, risk_state, risk_limits,
        )
        buy_orders = [o for o in orders if o["side"] == "buy"]
        assert all(o["stock_id"] != "2330" for o in buy_orders)


# ===================================================================
# 模擬執行
# ===================================================================

class TestExecuteOrders:

    def test_buy_execution(self, sample_price_cache):
        orders = [{
            "stock_id": "2317",
            "side": "buy",
            "shares": 5000,
            "price": 100.0,
            "strategy_name": "MA 交叉",
            "reason": "signal",
        }]
        holdings = pd.DataFrame()
        cash = 5_000_000

        executed, updated_holdings, updated_cash = _execute_orders(
            orders, holdings, cash, sample_price_cache, "2026-03-27",
        )
        assert len(executed) == 1
        assert executed[0]["side"] == "buy"
        assert executed[0]["shares"] == 5000
        # 現金減少
        assert updated_cash < cash
        # 新增持倉
        assert len(updated_holdings) == 1
        assert updated_holdings.iloc[0]["stock_id"] == "2317"

    def test_sell_execution(self, sample_price_cache):
        orders = [{
            "stock_id": "2330",
            "side": "sell",
            "shares": 5000,
            "price": 620.0,
            "strategy_name": "RSI 反轉",
            "reason": "signal",
        }]
        holdings = pd.DataFrame([{
            "stock_id": "2330", "shares": 5000, "entry_price": 600.0,
            "entry_date": "2025-12-01", "current_price": 620.0,
            "strategy_name": "RSI 反轉",
        }])
        cash = 3_000_000

        executed, updated_holdings, updated_cash = _execute_orders(
            orders, holdings, cash, sample_price_cache, "2026-03-27",
        )
        assert len(executed) == 1
        assert executed[0]["side"] == "sell"
        assert executed[0]["tax"] > 0  # 有證交稅
        assert executed[0]["realized_pnl"] is not None
        # 現金增加
        assert updated_cash > cash
        # 持倉清空
        assert len(updated_holdings) == 0

    def test_commission_and_tax(self, sample_price_cache):
        """驗證手續費和稅率計算"""
        orders = [{
            "stock_id": "2317", "side": "sell", "shares": 1000,
            "price": 100.0, "strategy_name": "test", "reason": "signal",
        }]
        holdings = pd.DataFrame([{
            "stock_id": "2317", "shares": 1000, "entry_price": 95.0,
            "entry_date": "2025-12-01", "current_price": 100.0,
            "strategy_name": "test",
        }])

        executed, _, _ = _execute_orders(
            orders, holdings, 5_000_000, sample_price_cache, "2026-03-27",
        )
        trade = executed[0]
        # 稅 = price * shares * 0.003 ≈ 100 * 1000 * 0.003 = 300
        assert trade["tax"] > 0
        assert trade["commission"] > 0

    def test_insufficient_cash_skips(self, sample_price_cache):
        """現金不足時跳過買單"""
        orders = [{
            "stock_id": "2317", "side": "buy", "shares": 10000,
            "price": 100.0, "strategy_name": "test", "reason": "signal",
        }]
        executed, _, cash = _execute_orders(
            orders, pd.DataFrame(), 500, sample_price_cache, "2026-03-27",
        )
        # 現金只有 500，買不了
        assert len(executed) == 0
