"""
回測引擎 — 含台灣市場手續費 / 證交稅 / 滑價
"""

import numpy as np
import pandas as pd

from analysis.strategies.base import BacktestResult, Strategy


class Backtester:
    """回測引擎"""

    def __init__(
        self,
        strategy: Strategy,
        capital: float = 1_000_000,
        commission: float = 0.001425,  # 台灣手續費 0.1425%
        tax: float = 0.003,            # 賣出證交稅 0.3%
        slippage: float = 0.001,       # 滑價 0.1%
    ):
        self.strategy = strategy
        self.initial_capital = capital
        self.commission = commission
        self.tax = tax
        self.slippage = slippage

    def run(self, data: pd.DataFrame) -> BacktestResult:
        """
        執行回測

        Parameters:
            data: 含 date, open, high, low, close, volume 的 DataFrame
        """
        if data.empty or len(data) < 2:
            return BacktestResult()

        df = self.strategy.generate_signals(data)
        if "signal" not in df.columns:
            return BacktestResult()

        # 回測主邏輯
        capital = self.initial_capital
        position = 0
        shares = 0
        entry_price = 0.0
        entry_date = None

        trades = []
        equity_history = []

        for i, row in df.iterrows():
            price = row["close"]
            date = row["date"]
            signal = row.get("signal", 0)

            if signal == 1 and position == 0:
                # 買入
                buy_price = price * (1 + self.slippage)
                buy_cost = buy_price * (1 + self.commission)
                shares = int(capital / buy_cost / 1000) * 1000  # 整張（1000股）
                if shares > 0:
                    total_cost = shares * buy_price * (1 + self.commission)
                    capital -= total_cost
                    position = 1
                    entry_price = buy_price
                    entry_date = date

            elif signal == -1 and position == 1:
                # 賣出
                sell_price = price * (1 - self.slippage)
                proceeds = shares * sell_price * (1 - self.commission - self.tax)
                pnl = proceeds - shares * entry_price * (1 + self.commission)
                pnl_pct = pnl / (shares * entry_price * (1 + self.commission))

                holding_days = (date - entry_date).days if entry_date else 0

                trades.append({
                    "entry_date": entry_date,
                    "exit_date": date,
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(sell_price, 2),
                    "shares": shares,
                    "pnl": round(pnl, 0),
                    "pnl_pct": round(pnl_pct * 100, 2),
                    "holding_days": holding_days,
                })

                capital += proceeds
                position = 0
                shares = 0
                entry_price = 0.0
                entry_date = None

            # 記錄權益
            if position == 1:
                equity = capital + shares * price
            else:
                equity = capital
            equity_history.append({"date": date, "equity": equity})

        # 建立 DataFrame
        equity_df = pd.DataFrame(equity_history)
        if equity_df.empty:
            return BacktestResult()

        equity_series = pd.Series(equity_df["equity"].values, index=equity_df["date"])
        trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()

        # 計算績效指標
        result = self._calc_metrics(equity_series, trades_df)
        return result

    def _calc_metrics(self, equity: pd.Series, trades: pd.DataFrame) -> BacktestResult:
        """計算績效指標"""
        if equity.empty:
            return BacktestResult()

        returns = equity.pct_change().dropna()

        # 總報酬率
        total_return = (equity.iloc[-1] / self.initial_capital) - 1

        # 年化報酬率
        days = (equity.index[-1] - equity.index[0]).days
        if days > 0:
            annual_return = (1 + total_return) ** (365 / days) - 1
        else:
            annual_return = 0.0

        # Sharpe Ratio (假設無風險利率 1.5%)
        rf = 0.015
        if len(returns) > 1 and returns.std() > 0:
            excess = returns.mean() - rf / 252
            sharpe_ratio = excess / returns.std() * np.sqrt(252)
        else:
            sharpe_ratio = 0.0

        # Sortino Ratio
        downside = returns[returns < 0]
        if len(downside) > 1 and downside.std() > 0:
            sortino_ratio = (returns.mean() - rf / 252) / downside.std() * np.sqrt(252)
        else:
            sortino_ratio = 0.0

        # 最大回撤
        peak = equity.cummax()
        drawdown = (equity - peak) / peak
        max_drawdown = drawdown.min()

        # 最大回撤持續天數
        dd_duration = 0
        max_dd_duration = 0
        for dd_val in drawdown:
            if dd_val < 0:
                dd_duration += 1
                max_dd_duration = max(max_dd_duration, dd_duration)
            else:
                dd_duration = 0

        # 交易統計
        trade_count = len(trades)
        if trade_count > 0:
            wins = trades[trades["pnl"] > 0]
            losses = trades[trades["pnl"] <= 0]
            win_rate = len(wins) / trade_count
            total_profit = wins["pnl"].sum() if not wins.empty else 0
            total_loss = abs(losses["pnl"].sum()) if not losses.empty else 0
            profit_factor = total_profit / total_loss if total_loss > 0 else float("inf")
            avg_holding_days = trades["holding_days"].mean()
        else:
            win_rate = 0.0
            profit_factor = 0.0
            avg_holding_days = 0.0

        # 月報酬率
        if len(returns) > 20:
            monthly = equity.resample("ME").last().pct_change().dropna()
        else:
            monthly = pd.Series(dtype=float)

        return BacktestResult(
            total_return=round(total_return, 4),
            annual_return=round(annual_return, 4),
            sharpe_ratio=round(sharpe_ratio, 2),
            sortino_ratio=round(sortino_ratio, 2),
            max_drawdown=round(max_drawdown, 4),
            max_drawdown_duration=max_dd_duration,
            win_rate=round(win_rate, 4),
            profit_factor=round(profit_factor, 2),
            trade_count=trade_count,
            avg_holding_days=round(avg_holding_days, 1),
            equity_curve=equity,
            drawdown_curve=drawdown,
            trades=trades,
            monthly_returns=monthly,
        )
