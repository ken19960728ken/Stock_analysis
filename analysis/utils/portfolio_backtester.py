"""
多策略組合回測引擎 — 等權 / Sharpe 最大化組合
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from analysis.strategies.base import BacktestResult, Strategy
from analysis.utils.backtester import Backtester


@dataclass
class PortfolioResult:
    strategy_results: dict = field(default_factory=dict)
    correlation_matrix: pd.DataFrame = field(default_factory=pd.DataFrame)
    combined_equity: pd.Series = field(default_factory=pd.Series)
    weights: dict = field(default_factory=dict)
    combined_return: float = 0.0
    combined_sharpe: float = 0.0


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

    def run(self, data: pd.DataFrame, equal_weight: bool = True) -> PortfolioResult:
        if not self.strategies or data.empty:
            return PortfolioResult()

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
        if equal_weight:
            weights = {name: 1.0 / n for name in equity_curves}
        else:
            weights = self._optimize_weights(returns_df)

        # 5. 等權/優化組合曲線
        weight_series = pd.Series(weights)
        combined_equity = equity_df.mul(weight_series).sum(axis=1)

        # 6. 計算組合績效
        combined_return = 0.0
        combined_sharpe = 0.0
        if len(combined_equity) > 1:
            combined_return = combined_equity.iloc[-1] / combined_equity.iloc[0] - 1
            comb_returns = combined_equity.pct_change().dropna()
            if len(comb_returns) > 1 and comb_returns.std() > 0:
                rf = 0.015
                excess = comb_returns.mean() - rf / 252
                combined_sharpe = excess / comb_returns.std() * np.sqrt(252)

        return PortfolioResult(
            strategy_results=results,
            correlation_matrix=corr_matrix,
            combined_equity=combined_equity,
            weights=weights,
            combined_return=round(combined_return, 4),
            combined_sharpe=round(combined_sharpe, 2),
        )

    def _optimize_weights(self, returns: pd.DataFrame) -> dict:
        """Sharpe 最大化（scipy.optimize.minimize）"""
        from scipy.optimize import minimize

        n = returns.shape[1]
        if n == 0:
            return {}

        names = returns.columns.tolist()
        mean_returns = returns.mean().values
        cov_matrix = returns.cov().values
        rf = 0.015 / 252

        def neg_sharpe(w):
            port_return = np.dot(w, mean_returns)
            port_vol = np.sqrt(np.dot(w.T, np.dot(cov_matrix, w)))
            if port_vol == 0:
                return 0.0
            return -(port_return - rf) / port_vol

        constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1}
        bounds = [(0, 1)] * n
        x0 = np.ones(n) / n

        result = minimize(neg_sharpe, x0, method="SLSQP",
                          bounds=bounds, constraints=constraints)

        if result.success:
            return {names[i]: round(float(result.x[i]), 4) for i in range(n)}
        else:
            return {name: 1.0 / n for name in names}
