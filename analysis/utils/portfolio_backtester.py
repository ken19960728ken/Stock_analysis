"""
多策略組合回測引擎 — 等權 / Sharpe 最大化 / 最小波動率 / 風險平價
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from analysis.strategies.base import BacktestResult, Strategy
from core.constants import RISK_FREE_RATE, TRADING_DAYS_PER_YEAR
from analysis.utils.backtester import Backtester

_EPS = 1e-12


@dataclass
class PortfolioResult:
    strategy_results: dict = field(default_factory=dict)
    correlation_matrix: pd.DataFrame = field(default_factory=pd.DataFrame)
    combined_equity: pd.Series = field(default_factory=pd.Series)
    weights: dict = field(default_factory=dict)
    combined_return: float = 0.0
    combined_sharpe: float = 0.0
    risk_contributions: dict = field(default_factory=dict)
    optimization_method: str = "equal"


class PortfolioBacktester:
    def __init__(
        self,
        strategies: list,
        capital: float = 1_000_000,
        commission: float = 0.001425,
        tax: float = 0.003,
        slippage: float = 0.001,
    ):
        self.strategies = strategies
        self.capital = capital
        self.commission = commission
        self.tax = tax
        self.slippage = slippage

    def run(self, data: pd.DataFrame, equal_weight: bool = True,
            weight_method: str = None) -> PortfolioResult:
        """
        Parameters:
            data: OHLCV DataFrame
            equal_weight: 向後相容，True → 等權分配（當 weight_method 未指定時生效）
            weight_method: "equal" | "max_sharpe" | "min_volatility" | "risk_parity"
                           若指定此參數，equal_weight 會被忽略
        """
        if not self.strategies or data.empty:
            return PortfolioResult()

        # 決定權重方法
        if weight_method is None:
            weight_method = "equal" if equal_weight else "max_sharpe"

        # 1. 對每個策略各建 Backtester 並 run()
        results = {}
        equity_curves = {}
        for strategy in self.strategies:
            bt = Backtester(
                strategy=strategy,
                capital=self.capital,
                commission=self.commission,
                tax=self.tax,
                slippage=self.slippage,
            )
            result = bt.run(data)
            results[strategy.name] = result
            if not result.equity_curve.empty:
                equity_curves[strategy.name] = result.equity_curve

        if not equity_curves:
            return PortfolioResult(strategy_results=results)

        # 2. 從各 equity_curve 計算 pct_change
        equity_df = pd.DataFrame(equity_curves)
        returns_df = equity_df.pct_change().dropna()

        # 3. 計算 correlation_matrix
        if len(equity_curves) >= 2 and len(returns_df) > 1:
            corr_matrix = returns_df.corr()
        else:
            corr_matrix = pd.DataFrame()

        # 4. 計算權重
        n = len(equity_curves)
        risk_contributions = {}

        if weight_method == "equal":
            weights = {name: 1.0 / n for name in equity_curves}
        else:
            weights, risk_contributions = self._optimize_weights(
                returns_df, weight_method
            )

        # 5. 等權/優化組合曲線
        weight_series = pd.Series(weights)
        combined_equity = equity_df.mul(weight_series).sum(axis=1)

        # 6. 計算組合績效
        combined_return = 0.0
        combined_sharpe = 0.0
        if len(combined_equity) > 1:
            combined_return = combined_equity.iloc[-1] / combined_equity.iloc[0] - 1
            comb_returns = combined_equity.pct_change().dropna()
            if len(comb_returns) > 1 and comb_returns.std() > _EPS:
                rf = RISK_FREE_RATE
                excess = comb_returns.mean() - rf / TRADING_DAYS_PER_YEAR
                combined_sharpe = excess / comb_returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)

        return PortfolioResult(
            strategy_results=results,
            correlation_matrix=corr_matrix,
            combined_equity=combined_equity,
            weights=weights,
            combined_return=round(combined_return, 4),
            combined_sharpe=round(combined_sharpe, 2),
            risk_contributions=risk_contributions,
            optimization_method=weight_method,
        )

    def _optimize_weights(self, returns: pd.DataFrame,
                          method: str) -> tuple:
        """委派給 portfolio_optimizer 模組"""
        from analysis.utils.portfolio_optimizer import (
            max_sharpe,
            min_volatility,
            risk_parity,
        )

        n = returns.shape[1]
        if n == 0:
            return {}, {}

        if method == "min_volatility":
            result = min_volatility(returns)
        elif method == "risk_parity":
            result = risk_parity(returns)
        else:
            result = max_sharpe(returns)

        return result.weights, result.risk_contributions
