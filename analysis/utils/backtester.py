"""
回測引擎 — 含台灣市場手續費 / 證交稅 / 滑價
"""

import numpy as np
import pandas as pd

from analysis.strategies.base import BacktestResult, Strategy
from core.constants import RISK_FREE_RATE, TRADING_DAYS_PER_YEAR

_EPS = 1e-12


class Backtester:
    """回測引擎"""

    def __init__(
        self,
        strategy: Strategy,
        capital: float = 1_000_000,
        commission: float = 0.001425,  # 台灣手續費 0.1425%
        tax: float = 0.003,            # 賣出證交稅 0.3%
        slippage: float = 0.001,       # 滑價 0.1%
        dynamic_slippage: bool = False,  # 啟用動態滑價
        impact_coeff: float = 0.1,      # 市場衝擊係數（Kyle lambda 簡化）
        max_participation: float = 1.0,  # 最大參與率（1.0 = 不限制）
        min_avg_volume: int = 0,         # 最低日均量（股），0 = 不限制
    ):
        self.strategy = strategy
        self.initial_capital = capital
        self.commission = commission
        self.tax = tax
        self.slippage = slippage
        self.dynamic_slippage = dynamic_slippage
        self.impact_coeff = impact_coeff
        self.max_participation = max_participation
        self.min_avg_volume = min_avg_volume

    def _calc_dynamic_slippage(self, shares: int, avg_volume: float) -> float:
        """動態滑價 = 基礎滑價 + 衝擊滑價

        學理來源:
        - Almgren & Chriss (2001) "Optimal Execution of Portfolio Transactions"
        - Kyle (1985) "Continuous Auctions and Insider Trading"

        base_slippage: 0.05% (bid-ask spread 的一半)
        impact: participation_rate × impact_coeff
        """
        base_slippage = 0.0005
        if avg_volume > 0:
            participation = shares / avg_volume
            impact = participation * self.impact_coeff
        else:
            impact = 0.01  # 無量資料，保守 1%
        return base_slippage + impact

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

        # 修正 Look-Ahead Bias：
        # 策略訊號基於收盤價計算，因此只能在「下一個交易日」執行。
        # 將 signal 向後 shift 1 日，使買賣在訊號產生的隔日以收盤價成交。
        df["signal"] = df["signal"].shift(1).fillna(0).astype(int)

        # 預計算 20 日均量（動態滑價 + 流動性限制用）
        if "volume" in df.columns:
            df["_avg_vol_20"] = df["volume"].rolling(20, min_periods=5).mean()
        else:
            df["_avg_vol_20"] = 0

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
            raw_avg_vol = row.get("_avg_vol_20", 0)
            avg_vol = float(raw_avg_vol) if pd.notna(raw_avg_vol) else 0.0

            if signal == 1 and position == 0:
                # 計算滑價
                if self.dynamic_slippage and avg_vol > 0:
                    # 先用初步估算的 shares 計算滑價
                    est_shares = int(capital / (price * (1 + self.commission)) / 1000) * 1000
                    slip = self._calc_dynamic_slippage(est_shares, avg_vol)
                else:
                    slip = self.slippage

                # 買入（訊號來自前一日收盤，本日執行）
                buy_price = price * (1 + slip)
                buy_cost = buy_price * (1 + self.commission)
                shares = int(capital / buy_cost / 1000) * 1000  # 整張（1000股）

                # 流動性限制
                if self.max_participation < 1.0 and avg_vol > 0:
                    max_shares = int(avg_vol * self.max_participation / 1000) * 1000
                    shares = min(shares, max_shares)
                if self.min_avg_volume > 0 and avg_vol < self.min_avg_volume:
                    shares = 0  # 流動性不足，放棄交易

                if shares > 0:
                    total_cost = shares * buy_price * (1 + self.commission)
                    capital -= total_cost
                    position = 1
                    entry_price = buy_price
                    entry_date = date

            elif signal == -1 and position == 1:
                # 計算賣出滑價
                if self.dynamic_slippage and avg_vol > 0:
                    slip = self._calc_dynamic_slippage(shares, avg_vol)
                else:
                    slip = self.slippage

                # 賣出（訊號來自前一日收盤，本日執行）
                sell_price = price * (1 - slip)
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

    def _calc_annual_breakdown(self, equity: pd.Series, trades: pd.DataFrame) -> pd.DataFrame:
        """按年度拆解績效"""
        if equity.empty:
            return pd.DataFrame()

        years = sorted(set(d.year for d in equity.index))
        rows = []
        for year in years:
            year_mask = [d.year == year for d in equity.index]
            year_eq = equity[year_mask]
            if len(year_eq) < 2:
                continue
            year_ret = year_eq.iloc[-1] / year_eq.iloc[0] - 1
            year_returns = year_eq.pct_change().dropna()

            # Sharpe
            if len(year_returns) > 1 and year_returns.std() > _EPS:
                year_sharpe = (
                    (year_returns.mean() - RISK_FREE_RATE / TRADING_DAYS_PER_YEAR)
                    / year_returns.std()
                    * np.sqrt(TRADING_DAYS_PER_YEAR)
                )
            else:
                year_sharpe = 0.0

            # Max Drawdown
            peak = year_eq.cummax()
            dd = (year_eq - peak) / peak
            year_mdd = dd.min()

            # 交易統計（該年度）
            if not trades.empty and "entry_date" in trades.columns:
                year_trades = trades[
                    trades["entry_date"].apply(
                        lambda d: d.year == year if hasattr(d, "year") else False
                    )
                ]
                year_trade_count = len(year_trades)
                if year_trade_count > 0:
                    year_win_rate = len(year_trades[year_trades["pnl"] > 0]) / year_trade_count
                else:
                    year_win_rate = 0.0
            else:
                year_trade_count = 0
                year_win_rate = 0.0

            rows.append({
                "year": year,
                "return": round(year_ret, 4),
                "sharpe": round(year_sharpe, 2),
                "max_drawdown": round(year_mdd, 4),
                "trade_count": year_trade_count,
                "win_rate": round(year_win_rate, 4),
            })

        return pd.DataFrame(rows)

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

        # Sharpe Ratio
        rf = RISK_FREE_RATE
        if len(returns) > 1 and returns.std() > _EPS:
            excess = returns.mean() - rf / TRADING_DAYS_PER_YEAR
            sharpe_ratio = excess / returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
        else:
            sharpe_ratio = 0.0

        # Sortino Ratio
        downside = returns[returns < 0]
        if len(downside) > 1 and downside.std() > _EPS:
            sortino_ratio = (returns.mean() - rf / TRADING_DAYS_PER_YEAR) / downside.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
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
            profit_factor = total_profit / total_loss if total_loss > _EPS else 999.0
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

        # 分年績效
        annual_breakdown = self._calc_annual_breakdown(equity, trades)

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
            annual_breakdown=annual_breakdown,
        )
