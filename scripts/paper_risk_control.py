"""
Paper Trading 風控模組 — 部位限制 + 回撤熔斷 + 策略暫停

提供前置檢查（下單前）和後置更新（交易後）兩類功能。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from analysis.utils.risk import calc_industry_concentration, calc_var
from core.logger import setup_logger

logger = setup_logger("paper_risk_control")


# ===================================================================
# 風控設定（不可變）
# ===================================================================

@dataclass(frozen=True)
class RiskLimits:
    """風控參數設定"""
    max_single_position_pct: float = 0.20   # 單檔部位上限（佔總資金比例）
    max_sector_pct: float = 0.40            # 同產業上限
    max_positions: int = 10                 # 最大同時持股數
    var_95_daily_limit: float = 0.02        # VaR(95%) 日限制（佔總資金比例）
    drawdown_pause: float = -0.10           # -10%: 暫停新建倉
    drawdown_halve: float = -0.15           # -15%: 全部減半
    drawdown_liquidate: float = -0.20       # -20%: 清倉
    consecutive_loss_limit: int = 5          # 策略連虧次數上限


# ===================================================================
# 風控狀態（可變，每日更新並持久化）
# ===================================================================

@dataclass
class RiskState:
    """風控狀態追蹤"""
    peak_equity: float = 0.0
    current_drawdown: float = 0.0
    is_paused: bool = False               # -10% 暫停新建倉
    is_halved: bool = False               # -15% 已執行減半
    is_liquidated: bool = False           # -20% 已執行清倉
    strategy_loss_counts: dict[str, int] = field(default_factory=dict)
    paused_strategies: set[str] = field(default_factory=set)

    def to_dict(self) -> dict:
        """序列化為可存入 DB 的 dict"""
        return {
            "peak_equity": self.peak_equity,
            "current_drawdown": self.current_drawdown,
            "is_paused": self.is_paused,
            "is_halved": self.is_halved,
            "is_liquidated": self.is_liquidated,
            "strategy_loss_counts": dict(self.strategy_loss_counts),
            "paused_strategies": sorted(self.paused_strategies),
        }

    @classmethod
    def from_dict(cls, data: dict) -> RiskState:
        """從 DB dict 還原"""
        return cls(
            peak_equity=float(data.get("peak_equity", 0)),
            current_drawdown=float(data.get("current_drawdown", 0)),
            is_paused=bool(data.get("is_paused", False)),
            is_halved=bool(data.get("is_halved", False)),
            is_liquidated=bool(data.get("is_liquidated", False)),
            strategy_loss_counts=dict(data.get("strategy_loss_counts", {})),
            paused_strategies=set(data.get("paused_strategies", [])),
        )

    @classmethod
    def from_db_row(cls, row: pd.Series) -> RiskState:
        """從 paper_daily_pnl 的一行還原"""
        # paused_strategies 和 strategy_loss_counts 以 JSONB 存在 DB
        paused = row.get("paused_strategies", [])
        if isinstance(paused, str):
            paused = json.loads(paused)
        loss_counts = row.get("strategy_loss_counts", {})
        if isinstance(loss_counts, str):
            loss_counts = json.loads(loss_counts)

        return cls(
            peak_equity=float(row.get("peak_equity", 0)),
            current_drawdown=float(row.get("drawdown_pct", 0)),
            is_paused=row.get("risk_status", "normal") in ("paused", "halved", "liquidated"),
            is_halved=row.get("risk_status", "normal") in ("halved", "liquidated"),
            is_liquidated=row.get("risk_status", "normal") == "liquidated",
            strategy_loss_counts=dict(loss_counts) if loss_counts else {},
            paused_strategies=set(paused) if paused else set(),
        )

    @property
    def risk_status_label(self) -> str:
        """取得風控狀態標籤"""
        if self.is_liquidated:
            return "liquidated"
        if self.is_halved:
            return "halved"
        if self.is_paused:
            return "paused"
        return "normal"


# ===================================================================
# 前置檢查（每筆 BUY 訂單調用）
# ===================================================================

def check_risk_constraints(
    order: dict,
    holdings: pd.DataFrame,
    cash: float,
    total_equity: float,
    risk_state: RiskState,
    risk_limits: RiskLimits,
    industry_map: pd.DataFrame | None = None,
    current_prices: dict[str, float] | None = None,
    portfolio_returns: pd.Series | None = None,
) -> tuple[bool, str]:
    """檢查單筆 BUY 訂單是否通過所有風控約束

    Args:
        order: {"stock_id": str, "shares": int, "price": float, "strategy_name": str}
        holdings: 當前持倉 DataFrame [stock_id, shares, ...]
        cash: 可用現金
        total_equity: 總資產（現金 + 持倉市值）
        risk_state: 當前風控狀態
        risk_limits: 風控參數
        industry_map: 產業分類 DataFrame [stock_id, sector]（可選）
        current_prices: {stock_id: price}（可選，產業集中度計算用）
        portfolio_returns: 近 60 日組合報酬率（可選，VaR 計算用）

    Returns:
        (allowed, reason) — allowed=True 表示通過，reason 為拒絕原因
    """
    stock_id = order["stock_id"]
    order_amount = order["shares"] * order["price"]
    strategy_name = order.get("strategy_name", "unknown")

    # 1. 回撤熔斷
    if risk_state.is_liquidated:
        return False, "回撤熔斷：已觸發 -20% 清倉，禁止所有交易"
    if risk_state.is_paused:
        return False, f"回撤熔斷：回撤 {risk_state.current_drawdown:.1%}，暫停新建倉"

    # 2. 策略暫停
    if strategy_name in risk_state.paused_strategies:
        count = risk_state.strategy_loss_counts.get(strategy_name, 0)
        return False, f"策略 {strategy_name} 已暫停（連虧 {count} 次）"

    # 3. 持倉數量上限
    current_count = len(holdings) if not holdings.empty else 0
    if current_count >= risk_limits.max_positions:
        return False, f"持倉已達上限 {risk_limits.max_positions} 檔"

    # 4. 現金不足
    if order_amount > cash:
        return False, f"現金不足：需 {order_amount:,.0f}，可用 {cash:,.0f}"

    # 5. 單檔比重
    if total_equity > 0:
        position_pct = order_amount / total_equity
        if position_pct > risk_limits.max_single_position_pct:
            return False, (
                f"單檔比重 {position_pct:.1%} 超過上限 "
                f"{risk_limits.max_single_position_pct:.0%}"
            )

    # 6. 產業集中度
    if industry_map is not None and current_prices is not None and not holdings.empty:
        # 模擬加入新持倉後的產業集中度
        new_row = pd.DataFrame([{"stock_id": stock_id, "shares": order["shares"]}])
        hypothetical = pd.concat(
            [holdings[["stock_id", "shares"]], new_row], ignore_index=True,
        )
        updated_prices = {**current_prices, stock_id: order["price"]}
        result = calc_industry_concentration(
            hypothetical, updated_prices, industry_map, risk_limits.max_sector_pct,
        )
        if result.get("warnings"):
            return False, f"產業集中度超標：{result['warnings'][0]}"

    # 7. VaR 限制
    if portfolio_returns is not None and len(portfolio_returns) >= 20:
        var_95 = calc_var(portfolio_returns, 0.95)
        if abs(var_95) > risk_limits.var_95_daily_limit:
            return False, (
                f"VaR(95%) = {abs(var_95):.2%} 超過上限 "
                f"{risk_limits.var_95_daily_limit:.0%}"
            )

    return True, "通過"


# ===================================================================
# 後置更新（每日交易後調用）
# ===================================================================

def update_drawdown(
    equity: float,
    risk_state: RiskState,
    risk_limits: RiskLimits,
) -> list[dict]:
    """更新峰值和回撤追蹤，觸發熔斷

    Args:
        equity: 當前總資產
        risk_state: 風控狀態（會被就地修改）
        risk_limits: 風控參數

    Returns: 觸發的告警列表 [{type, severity, message}, ...]
    """
    alerts: list[dict] = []

    # 更新峰值
    if equity > risk_state.peak_equity:
        risk_state.peak_equity = equity
        # 回到新高，重設熔斷狀態
        if risk_state.is_paused or risk_state.is_halved:
            risk_state.is_paused = False
            risk_state.is_halved = False
            risk_state.is_liquidated = False
            alerts.append({
                "type": "drawdown_reset",
                "severity": "info",
                "message": f"資產創新高 {equity:,.0f}，重設回撤熔斷",
            })

    # 計算回撤
    if risk_state.peak_equity > 0:
        risk_state.current_drawdown = (equity - risk_state.peak_equity) / risk_state.peak_equity
    else:
        risk_state.current_drawdown = 0.0

    # 檢查熔斷
    dd = risk_state.current_drawdown

    if dd <= risk_limits.drawdown_liquidate and not risk_state.is_liquidated:
        risk_state.is_liquidated = True
        risk_state.is_halved = True
        risk_state.is_paused = True
        alerts.append({
            "type": "drawdown_liquidate",
            "severity": "critical",
            "message": f"回撤 {dd:.1%} 觸發清倉熔斷（閾值 {risk_limits.drawdown_liquidate:.0%}）",
        })
    elif dd <= risk_limits.drawdown_halve and not risk_state.is_halved:
        risk_state.is_halved = True
        risk_state.is_paused = True
        alerts.append({
            "type": "drawdown_halve",
            "severity": "critical",
            "message": f"回撤 {dd:.1%} 觸發減半熔斷（閾值 {risk_limits.drawdown_halve:.0%}）",
        })
    elif dd <= risk_limits.drawdown_pause and not risk_state.is_paused:
        risk_state.is_paused = True
        alerts.append({
            "type": "drawdown_pause",
            "severity": "warning",
            "message": f"回撤 {dd:.1%} 觸發暫停新建倉（閾值 {risk_limits.drawdown_pause:.0%}）",
        })

    return alerts


def update_strategy_losses(
    trades: list[dict],
    risk_state: RiskState,
    risk_limits: RiskLimits,
) -> list[dict]:
    """追蹤策略連續虧損，觸發策略暫停

    Args:
        trades: 今日已成交的賣出交易 [{strategy_name, realized_pnl, ...}]
        risk_state: 風控狀態（會被就地修改）
        risk_limits: 風控參數

    Returns: 觸發的告警列表
    """
    alerts: list[dict] = []

    for trade in trades:
        if trade.get("side") != "sell":
            continue

        strategy = trade.get("strategy_name", "unknown")
        pnl = trade.get("realized_pnl", 0)

        if pnl < 0:
            # 連虧計數 +1
            current = risk_state.strategy_loss_counts.get(strategy, 0)
            risk_state.strategy_loss_counts[strategy] = current + 1

            if risk_state.strategy_loss_counts[strategy] >= risk_limits.consecutive_loss_limit:
                if strategy not in risk_state.paused_strategies:
                    risk_state.paused_strategies.add(strategy)
                    alerts.append({
                        "type": "strategy_pause",
                        "severity": "warning",
                        "message": (
                            f"策略 {strategy} 連虧 "
                            f"{risk_state.strategy_loss_counts[strategy]} 次，已暫停"
                        ),
                    })
        else:
            # 獲利或打平，重設連虧計數
            risk_state.strategy_loss_counts[strategy] = 0
            if strategy in risk_state.paused_strategies:
                risk_state.paused_strategies.discard(strategy)
                alerts.append({
                    "type": "strategy_resume",
                    "severity": "info",
                    "message": f"策略 {strategy} 獲利，解除暫停",
                })

    return alerts


# ===================================================================
# 熔斷訂單生成
# ===================================================================

def generate_halve_orders(holdings: pd.DataFrame) -> list[dict]:
    """產生減半賣出訂單（-15% 熔斷觸發時）

    將每個持倉賣出約一半，取整到 1000 股（台股整張）。

    Args:
        holdings: 持倉 DataFrame [stock_id, shares, current_price, strategy_name, ...]

    Returns: list of order dicts
    """
    orders: list[dict] = []
    for _, row in holdings.iterrows():
        shares = int(row["shares"])
        half = (shares // 2 // 1000) * 1000
        if half <= 0:
            # 持股不足 2000 股（2 張），全部賣出
            half = shares
        orders.append({
            "stock_id": row["stock_id"],
            "side": "sell",
            "shares": half,
            "price": float(row.get("current_price", 0)),
            "strategy_name": row.get("strategy_name", "unknown"),
            "reason": "risk_halve",
        })
    return orders


def generate_liquidate_orders(holdings: pd.DataFrame) -> list[dict]:
    """產生清倉賣出訂單（-20% 熔斷觸發時）

    Args:
        holdings: 持倉 DataFrame

    Returns: list of order dicts
    """
    orders: list[dict] = []
    for _, row in holdings.iterrows():
        orders.append({
            "stock_id": row["stock_id"],
            "side": "sell",
            "shares": int(row["shares"]),
            "price": float(row.get("current_price", 0)),
            "strategy_name": row.get("strategy_name", "unknown"),
            "reason": "risk_liquidate",
        })
    return orders
