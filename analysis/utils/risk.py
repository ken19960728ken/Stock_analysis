"""
風險指標計算模組 — VaR, CVaR, Sharpe, Sortino, Beta, 回撤分析
"""

import numpy as np
import pandas as pd


def calc_var(returns: pd.Series, confidence: float = 0.95) -> float:
    """Value at Risk (歷史模擬法)"""
    if returns.empty:
        return 0.0
    return float(np.percentile(returns.dropna(), (1 - confidence) * 100))


def calc_cvar(returns: pd.Series, confidence: float = 0.95) -> float:
    """Conditional VaR (Expected Shortfall)"""
    if returns.empty:
        return 0.0
    var = calc_var(returns, confidence)
    tail = returns[returns <= var]
    return float(tail.mean()) if not tail.empty else var


def calc_sharpe(returns: pd.Series, rf: float = 0.015) -> float:
    """Sharpe Ratio (年化)"""
    if len(returns) < 2 or returns.std() == 0:
        return 0.0
    excess = returns.mean() - rf / 252
    return float(excess / returns.std() * np.sqrt(252))


def calc_sortino(returns: pd.Series, rf: float = 0.015) -> float:
    """Sortino Ratio (年化)"""
    if len(returns) < 2:
        return 0.0
    downside = returns[returns < 0]
    if downside.empty or downside.std() == 0:
        return 0.0
    return float((returns.mean() - rf / 252) / downside.std() * np.sqrt(252))


def calc_beta(stock_returns: pd.Series, market_returns: pd.Series) -> float:
    """Beta 係數"""
    aligned = pd.concat([stock_returns, market_returns], axis=1).dropna()
    if len(aligned) < 2:
        return 0.0
    cov = aligned.cov().iloc[0, 1]
    var = market_returns.var()
    return float(cov / var) if var > 0 else 0.0


def calc_alpha(stock_returns: pd.Series, market_returns: pd.Series,
               rf: float = 0.015) -> float:
    """Alpha (Jensen's Alpha，年化)"""
    beta = calc_beta(stock_returns, market_returns)
    stock_annual = stock_returns.mean() * 252
    market_annual = market_returns.mean() * 252
    return float(stock_annual - (rf + beta * (market_annual - rf)))


def calc_max_drawdown(equity: pd.Series) -> tuple:
    """
    最大回撤分析

    Returns:
        (max_drawdown, drawdown_series, max_dd_start, max_dd_end, max_dd_duration_days)
    """
    if equity.empty:
        return 0.0, pd.Series(dtype=float), None, None, 0

    peak = equity.cummax()
    drawdown = (equity - peak) / peak

    max_dd = drawdown.min()

    # 找最大回撤的起止點
    max_dd_idx = drawdown.idxmin()
    peak_idx = equity[:max_dd_idx].idxmax() if max_dd_idx is not None else None

    # 回撤持續天數
    dd_duration = 0
    if peak_idx is not None and max_dd_idx is not None:
        dd_duration = (max_dd_idx - peak_idx).days

    return max_dd, drawdown, peak_idx, max_dd_idx, dd_duration


def calc_portfolio_volatility(weights: np.ndarray, cov_matrix: pd.DataFrame) -> float:
    """投資組合波動率"""
    port_var = np.dot(weights, np.dot(cov_matrix.values, weights))
    return float(np.sqrt(port_var * 252))


def calc_information_ratio(stock_returns: pd.Series, benchmark_returns: pd.Series) -> float:
    """Information Ratio"""
    excess = stock_returns - benchmark_returns
    aligned = excess.dropna()
    if aligned.empty or aligned.std() == 0:
        return 0.0
    return float(aligned.mean() / aligned.std() * np.sqrt(252))


def calc_calmar_ratio(annual_return: float, max_drawdown: float) -> float:
    """Calmar Ratio"""
    if max_drawdown == 0:
        return 0.0
    return float(annual_return / abs(max_drawdown))


def portfolio_risk_report(
    holdings: pd.DataFrame,
    price_data: dict,
    market_returns: pd.Series = None,
) -> dict:
    """
    持倉風險報告

    Parameters:
        holdings: DataFrame with columns [stock_id, shares, cost_price]
        price_data: {stock_id: price_df} mapping
        market_returns: 大盤日報酬率

    Returns:
        dict of risk metrics
    """
    report = {}

    # 計算個股報酬率
    all_returns = {}
    current_prices = {}
    for _, row in holdings.iterrows():
        sid = row["stock_id"]
        if sid in price_data and not price_data[sid].empty:
            pdf = price_data[sid]
            returns = pdf["close"].pct_change().dropna()
            all_returns[sid] = returns
            current_prices[sid] = pdf["close"].iloc[-1]
        else:
            current_prices[sid] = row.get("cost_price", 0)

    # 持倉市值
    total_value = 0
    positions = []
    for _, row in holdings.iterrows():
        sid = row["stock_id"]
        shares = row["shares"]
        cost = row["cost_price"]
        current = current_prices.get(sid, cost)
        mv = shares * current
        pnl = (current - cost) * shares
        pnl_pct = (current / cost - 1) * 100 if cost > 0 else 0
        total_value += mv
        positions.append({
            "stock_id": sid,
            "shares": shares,
            "cost_price": cost,
            "current_price": round(current, 2),
            "market_value": round(mv, 0),
            "pnl": round(pnl, 0),
            "pnl_pct": round(pnl_pct, 2),
        })
    report["positions"] = pd.DataFrame(positions)
    report["total_value"] = total_value

    # 投資組合報酬率
    if all_returns:
        returns_df = pd.DataFrame(all_returns).dropna()
        if not returns_df.empty:
            weights = np.array([
                holdings.loc[holdings["stock_id"] == sid, "shares"].values[0]
                * current_prices.get(sid, 0) / total_value
                for sid in returns_df.columns
            ])
            port_returns = returns_df.dot(weights)

            report["VaR_95"] = round(calc_var(port_returns, 0.95) * 100, 2)
            report["CVaR_95"] = round(calc_cvar(port_returns, 0.95) * 100, 2)
            report["volatility"] = round(port_returns.std() * np.sqrt(252) * 100, 2)
            report["sharpe"] = round(calc_sharpe(port_returns), 2)

            if market_returns is not None:
                report["beta"] = round(calc_beta(port_returns, market_returns), 2)
                report["alpha"] = round(calc_alpha(port_returns, market_returns), 4)

            # 相關性矩陣
            report["correlation"] = returns_df.corr()

    return report
