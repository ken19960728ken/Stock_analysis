"""回測工具 — 交易成本敏感度分析、策略比較"""

import pandas as pd
from analysis.strategies.base import Strategy
from analysis.utils.backtester import Backtester


def cost_sensitivity_analysis(
    strategy: Strategy,
    data: pd.DataFrame,
    capital: float = 1_000_000,
    commission_range: tuple = (0.001, 0.001425, 0.002),
    slippage_range: tuple = (0.001, 0.003, 0.005, 0.01),
    tax: float = 0.003,
) -> pd.DataFrame:
    """對不同交易成本組合跑回測，回傳績效矩陣

    Returns:
        DataFrame with columns:
        commission, slippage, total_return, annual_return, sharpe_ratio,
        max_drawdown, win_rate, trade_count, profit_factor
    """
    results = []
    for comm in commission_range:
        for slip in slippage_range:
            bt = Backtester(
                strategy=strategy,
                capital=capital,
                commission=comm,
                tax=tax,
                slippage=slip,
            )
            result = bt.run(data)
            results.append({
                "commission": comm,
                "slippage": slip,
                "total_return": result.total_return,
                "annual_return": result.annual_return,
                "sharpe_ratio": result.sharpe_ratio,
                "max_drawdown": result.max_drawdown,
                "win_rate": result.win_rate,
                "trade_count": result.trade_count,
                "profit_factor": result.profit_factor,
            })
    return pd.DataFrame(results)


def breakeven_cost(
    strategy: Strategy,
    data: pd.DataFrame,
    capital: float = 1_000_000,
    tax: float = 0.003,
    max_slippage: float = 0.05,
    step: float = 0.001,
) -> float:
    """找出策略能承受的最大總交易成本（手續費+滑價）

    以 total_return > 0 為門檻，二分搜尋最大可承受的 slippage。
    commission 固定為 0.001425（台灣標準）。

    Returns:
        最大可承受 slippage（超過此值策略虧損）。若策略在 0 滑價都虧損則回傳 0。
    """
    commission = 0.001425

    # 先確認零滑價是否有正報酬
    bt = Backtester(
        strategy=strategy,
        capital=capital,
        commission=commission,
        tax=tax,
        slippage=0,
    )
    r = bt.run(data)
    if r.total_return <= 0:
        return 0.0

    # 二分搜尋
    lo, hi = 0.0, max_slippage
    for _ in range(20):  # 精度到 0.00005
        mid = (lo + hi) / 2
        bt = Backtester(
            strategy=strategy,
            capital=capital,
            commission=commission,
            tax=tax,
            slippage=mid,
        )
        r = bt.run(data)
        if r.total_return > 0:
            lo = mid
        else:
            hi = mid
    return round(lo, 5)
