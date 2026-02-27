"""
投資組合最佳化模組 — Max Sharpe / Min Vol / Risk Parity / Black-Litterman
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from core.constants import RISK_FREE_RATE, TRADING_DAYS_PER_YEAR

_EPS = 1e-12


@dataclass
class OptimizationResult:
    weights: dict = field(default_factory=dict)
    expected_return: float = 0.0
    expected_volatility: float = 0.0
    sharpe_ratio: float = 0.0
    method: str = ""
    risk_contributions: dict = field(default_factory=dict)


def _annualize(mean_ret, cov, trading_days=TRADING_DAYS_PER_YEAR):
    return mean_ret * trading_days, cov * trading_days


def _portfolio_stats(w, mean_ret, cov, rf=RISK_FREE_RATE):
    port_ret = np.dot(w, mean_ret)
    port_vol = np.sqrt(np.dot(w, np.dot(cov, w)))
    sharpe = (port_ret - rf) / port_vol if port_vol > _EPS else 0.0
    return port_ret, port_vol, sharpe


def _risk_contribution(w, cov):
    """計算各資產的風險貢獻"""
    port_vol = np.sqrt(np.dot(w, np.dot(cov, w)))
    if port_vol < _EPS:
        return np.zeros_like(w)
    marginal = np.dot(cov, w) / port_vol
    rc = w * marginal
    return rc


def max_sharpe(returns: pd.DataFrame, rf: float = RISK_FREE_RATE,
               constraints: dict = None) -> OptimizationResult:
    """Sharpe Ratio 最大化"""
    names = returns.columns.tolist()
    n = len(names)
    if n == 0:
        return OptimizationResult(method="max_sharpe")

    mean_ret, cov = _annualize(returns.mean().values, returns.cov().values)

    def neg_sharpe(w):
        ret, vol, _ = _portfolio_stats(w, mean_ret, cov, rf)
        return -(ret - rf) / vol if vol > _EPS else 0.0

    cons = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
    bounds = [(constraints or {}).get("min_weight", 0),
              (constraints or {}).get("max_weight", 1)]
    bounds = [tuple(bounds)] * n
    x0 = np.ones(n) / n

    result = minimize(neg_sharpe, x0, method="SLSQP",
                      bounds=bounds, constraints=cons)
    w = result.x if result.success else np.ones(n) / n

    ret, vol, sharpe = _portfolio_stats(w, mean_ret, cov, rf)
    rc = _risk_contribution(w, cov * TRADING_DAYS_PER_YEAR)
    weights_dict = {names[i]: round(float(w[i]), 4) for i in range(n)}
    rc_dict = {names[i]: round(float(rc[i]), 4) for i in range(n)}

    return OptimizationResult(
        weights=weights_dict,
        expected_return=round(float(ret), 4),
        expected_volatility=round(float(vol), 4),
        sharpe_ratio=round(float(sharpe), 2),
        method="max_sharpe",
        risk_contributions=rc_dict,
    )


def min_volatility(returns: pd.DataFrame,
                   constraints: dict = None) -> OptimizationResult:
    """最小波動率組合"""
    names = returns.columns.tolist()
    n = len(names)
    if n == 0:
        return OptimizationResult(method="min_volatility")

    mean_ret, cov = _annualize(returns.mean().values, returns.cov().values)

    def portfolio_vol(w):
        return np.sqrt(np.dot(w, np.dot(cov, w)))

    cons = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
    bounds = [(constraints or {}).get("min_weight", 0),
              (constraints or {}).get("max_weight", 1)]
    bounds = [tuple(bounds)] * n
    x0 = np.ones(n) / n

    result = minimize(portfolio_vol, x0, method="SLSQP",
                      bounds=bounds, constraints=cons)
    w = result.x if result.success else np.ones(n) / n

    ret, vol, sharpe = _portfolio_stats(w, mean_ret, cov)
    rc = _risk_contribution(w, cov)
    weights_dict = {names[i]: round(float(w[i]), 4) for i in range(n)}
    rc_dict = {names[i]: round(float(rc[i]), 4) for i in range(n)}

    return OptimizationResult(
        weights=weights_dict,
        expected_return=round(float(ret), 4),
        expected_volatility=round(float(vol), 4),
        sharpe_ratio=round(float(sharpe), 2),
        method="min_volatility",
        risk_contributions=rc_dict,
    )


def risk_parity(returns: pd.DataFrame) -> OptimizationResult:
    """風險平價 — 讓每個資產的風險貢獻相等"""
    names = returns.columns.tolist()
    n = len(names)
    if n == 0:
        return OptimizationResult(method="risk_parity")

    mean_ret, cov = _annualize(returns.mean().values, returns.cov().values)
    target_rc = 1.0 / n

    def risk_parity_obj(w):
        rc = _risk_contribution(w, cov)
        port_vol = np.sqrt(np.dot(w, np.dot(cov, w)))
        if port_vol < _EPS:
            return 0.0
        rc_pct = rc / port_vol
        return np.sum((rc_pct - target_rc) ** 2)

    cons = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
    bounds = [(0.01, 1)] * n
    x0 = np.ones(n) / n

    result = minimize(risk_parity_obj, x0, method="SLSQP",
                      bounds=bounds, constraints=cons)
    w = result.x if result.success else np.ones(n) / n

    ret, vol, sharpe = _portfolio_stats(w, mean_ret, cov)
    rc = _risk_contribution(w, cov)
    weights_dict = {names[i]: round(float(w[i]), 4) for i in range(n)}
    rc_dict = {names[i]: round(float(rc[i]), 4) for i in range(n)}

    return OptimizationResult(
        weights=weights_dict,
        expected_return=round(float(ret), 4),
        expected_volatility=round(float(vol), 4),
        sharpe_ratio=round(float(sharpe), 2),
        method="risk_parity",
        risk_contributions=rc_dict,
    )


def black_litterman(returns: pd.DataFrame, market_caps: dict = None,
                    views: dict = None, tau: float = 0.05,
                    rf: float = RISK_FREE_RATE) -> OptimizationResult:
    """
    Black-Litterman 模型

    Parameters:
        returns: 各資產日報酬率
        market_caps: {asset_name: market_cap}，若 None 則用等權
        views: {asset_name: expected_excess_return}，若 None 則用市場均衡
        tau: 不確定性係數
        rf: 無風險利率
    """
    names = returns.columns.tolist()
    n = len(names)
    if n == 0:
        return OptimizationResult(method="black_litterman")

    mean_ret_daily = returns.mean().values
    cov_daily = returns.cov().values
    cov = cov_daily * TRADING_DAYS_PER_YEAR

    # 市場均衡權重
    if market_caps and all(name in market_caps for name in names):
        total_cap = sum(market_caps[name] for name in names)
        w_mkt = np.array([market_caps[name] / total_cap for name in names])
    else:
        w_mkt = np.ones(n) / n

    # 隱含均衡超額報酬
    delta = 2.5  # risk aversion coefficient
    pi = delta * np.dot(cov, w_mkt)

    if views:
        # 建構 P (pick matrix) 和 Q (view vector)
        view_assets = [name for name in names if name in views]
        k = len(view_assets)
        if k > 0:
            P = np.zeros((k, n))
            Q = np.zeros(k)
            for i, asset in enumerate(view_assets):
                j = names.index(asset)
                P[i, j] = 1.0
                Q[i] = views[asset]

            # 觀點不確定性矩陣
            omega = np.diag(np.diag(tau * P @ cov @ P.T))

            # BL 後驗期望報酬
            tau_cov_inv = np.linalg.inv(tau * cov)
            omega_inv = np.linalg.inv(omega)
            bl_mean = np.linalg.inv(tau_cov_inv + P.T @ omega_inv @ P) @ \
                      (tau_cov_inv @ pi + P.T @ omega_inv @ Q)
        else:
            bl_mean = pi
    else:
        bl_mean = pi

    # 用 BL 均值做 max Sharpe
    def neg_sharpe(w):
        ret = np.dot(w, bl_mean)
        vol = np.sqrt(np.dot(w, np.dot(cov, w)))
        return -(ret - rf) / vol if vol > _EPS else 0.0

    cons = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
    bounds = [(0, 1)] * n
    x0 = w_mkt.copy()

    result = minimize(neg_sharpe, x0, method="SLSQP",
                      bounds=bounds, constraints=cons)
    w = result.x if result.success else w_mkt

    ann_ret = np.dot(w, bl_mean)
    ann_vol = np.sqrt(np.dot(w, np.dot(cov, w)))
    sharpe = (ann_ret - rf) / ann_vol if ann_vol > _EPS else 0.0
    rc = _risk_contribution(w, cov)
    weights_dict = {names[i]: round(float(w[i]), 4) for i in range(n)}
    rc_dict = {names[i]: round(float(rc[i]), 4) for i in range(n)}

    return OptimizationResult(
        weights=weights_dict,
        expected_return=round(float(ann_ret), 4),
        expected_volatility=round(float(ann_vol), 4),
        sharpe_ratio=round(float(sharpe), 2),
        method="black_litterman",
        risk_contributions=rc_dict,
    )


def efficient_frontier(returns: pd.DataFrame, n_points: int = 50,
                       rf: float = RISK_FREE_RATE) -> pd.DataFrame:
    """計算效率前緣上的點"""
    names = returns.columns.tolist()
    n = len(names)
    if n == 0:
        return pd.DataFrame()

    mean_ret, cov = _annualize(returns.mean().values, returns.cov().values)

    # 先求最小和最大報酬端點
    min_result = min_volatility(returns)
    max_result = max_sharpe(returns, rf)

    target_returns = np.linspace(
        min_result.expected_return,
        max(max_result.expected_return, min_result.expected_return + 0.01),
        n_points,
    )

    frontier = []
    for target_ret in target_returns:
        def portfolio_vol(w):
            return np.sqrt(np.dot(w, np.dot(cov, w)))

        cons = [
            {"type": "eq", "fun": lambda w: np.sum(w) - 1},
            {"type": "eq", "fun": lambda w, tr=target_ret: np.dot(w, mean_ret) - tr},
        ]
        bounds = [(0, 1)] * n
        x0 = np.ones(n) / n
        result = minimize(portfolio_vol, x0, method="SLSQP",
                          bounds=bounds, constraints=cons)
        if result.success:
            vol = float(result.fun)
            ret = float(target_ret)
            sharpe = (ret - rf) / vol if vol > _EPS else 0.0
            frontier.append({"return": ret, "volatility": vol, "sharpe": sharpe})

    return pd.DataFrame(frontier)
