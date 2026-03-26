"""
多股票組合回測引擎 — 策略同時掃描 N 支股票，依資金分配持有

與現有 Backtester（單股回測）和 PortfolioBacktester（多策略單股回測）不同，
此模組處理的是「一個策略 × 多支股票 × 資金分配」的場景。

Usage:
    from analysis.utils.multi_stock_backtester import MultiStockBacktester

    bt = MultiStockBacktester(
        strategy=MACrossStrategy(),
        max_positions=10,
        position_sizing="equal",
    )
    result = bt.run(stock_data_dict)  # {stock_id: DataFrame}
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from analysis.strategies.base import Strategy
from core.constants import RISK_FREE_RATE, TRADING_DAYS_PER_YEAR

_EPS = 1e-12


@dataclass
class MultiStockResult:
    """多股組合回測結果"""
    total_return: float = 0.0
    annual_return: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    trade_count: int = 0
    avg_holding_days: float = 0.0
    max_concurrent_positions: int = 0
    avg_concurrent_positions: float = 0.0
    turnover_rate: float = 0.0           # 年化換手率
    equity_curve: pd.Series = field(default_factory=pd.Series)
    drawdown_curve: pd.Series = field(default_factory=pd.Series)
    trades: pd.DataFrame = field(default_factory=pd.DataFrame)
    monthly_returns: pd.Series = field(default_factory=pd.Series)
    annual_breakdown: pd.DataFrame = field(default_factory=pd.DataFrame)
    position_history: pd.DataFrame = field(default_factory=pd.DataFrame)  # 每日持股明細


class MultiStockBacktester:
    """多股票組合回測"""

    def __init__(
        self,
        strategy: Strategy,
        capital: float = 1_000_000,
        max_positions: int = 10,
        position_sizing: str = "equal",  # "equal" | "score"
        commission: float = 0.001425,
        tax: float = 0.003,
        slippage: float = 0.001,
        dynamic_slippage: bool = False,
        impact_coeff: float = 0.1,
        max_participation: float = 1.0,
        min_avg_volume: int = 0,
        rebalance_freq: int = 0,         # 0 = 只在訊號變化時交易
    ):
        self.strategy = strategy
        self.initial_capital = capital
        self.max_positions = max_positions
        self.position_sizing = position_sizing
        self.commission = commission
        self.tax = tax
        self.slippage = slippage
        self.dynamic_slippage = dynamic_slippage
        self.impact_coeff = impact_coeff
        self.max_participation = max_participation
        self.min_avg_volume = min_avg_volume
        self.rebalance_freq = rebalance_freq

    def run(self, stock_data: dict[str, pd.DataFrame]) -> MultiStockResult:
        """
        執行多股組合回測

        Parameters:
            stock_data: {stock_id: DataFrame(date, open, high, low, close, volume, ...)}
                        每支股票的資料需已包含策略所需的額外欄位（如籌碼、基本面）

        Returns:
            MultiStockResult
        """
        if not stock_data:
            return MultiStockResult()

        # Step 1: 對每支股票 generate_signals
        signals = {}
        for stock_id, df in stock_data.items():
            if df.empty or len(df) < 2:
                continue
            sig_df = self.strategy.generate_signals(df.copy())
            if "signal" not in sig_df.columns:
                continue
            # Look-Ahead Bias 修正
            sig_df["signal"] = sig_df["signal"].shift(1).fillna(0).astype(int)
            # 預計算 20 日均量
            if "volume" in sig_df.columns:
                sig_df["_avg_vol_20"] = (
                    sig_df["volume"].rolling(20, min_periods=5).mean()
                )
            else:
                sig_df["_avg_vol_20"] = 0
            signals[stock_id] = sig_df

        if not signals:
            return MultiStockResult()

        # Step 2: 建立統一日期軸
        all_dates = sorted(set(
            d for df in signals.values()
            for d in df["date"].tolist()
        ))

        # Step 3: 逐日模擬
        capital = self.initial_capital
        positions: dict[str, dict] = {}
        # positions = {stock_id: {"shares": N, "entry_price": P, "entry_date": D}}
        trades: list[dict] = []
        equity_history: list[dict] = []
        position_count_history: list[int] = []

        for date in all_dates:
            # 收集當日所有股票的訊號和價格
            daily_info: dict = {}
            for stock_id, df in signals.items():
                day_row = df[df["date"] == date]
                if day_row.empty:
                    continue
                row = day_row.iloc[0]
                daily_info[stock_id] = row

            # --- 賣出：檢查持有部位中有 signal=-1 的 ---
            for stock_id in list(positions.keys()):
                if stock_id not in daily_info:
                    continue
                row = daily_info[stock_id]
                if row.get("signal", 0) == -1:
                    pos = positions[stock_id]
                    price = row["close"]
                    avg_vol = row.get("_avg_vol_20", 0)
                    avg_vol = avg_vol if pd.notna(avg_vol) else 0

                    slip = self._get_slippage(pos["shares"], avg_vol)
                    sell_price = price * (1 - slip)
                    proceeds = (
                        pos["shares"] * sell_price
                        * (1 - self.commission - self.tax)
                    )
                    cost_basis = (
                        pos["shares"] * pos["entry_price"]
                        * (1 + self.commission)
                    )
                    pnl = proceeds - cost_basis
                    pnl_pct = pnl / cost_basis if cost_basis > 0 else 0

                    holding_days = (
                        (date - pos["entry_date"]).days
                        if pos["entry_date"]
                        else 0
                    )

                    trades.append({
                        "stock_id": stock_id,
                        "entry_date": pos["entry_date"],
                        "exit_date": date,
                        "entry_price": round(pos["entry_price"], 2),
                        "exit_price": round(sell_price, 2),
                        "shares": pos["shares"],
                        "pnl": round(pnl, 0),
                        "pnl_pct": round(pnl_pct * 100, 2),
                        "holding_days": holding_days,
                    })

                    capital += proceeds
                    del positions[stock_id]

            # --- 買入：收集 signal=1 且未持有的 ---
            buy_candidates: list[tuple] = []
            for stock_id, row in daily_info.items():
                if stock_id in positions:
                    continue
                if row.get("signal", 0) == 1:
                    buy_candidates.append((stock_id, row))

            # 排序（如果策略有提供 score 欄位，依 score 排名；否則保持原順序）
            if buy_candidates:
                if self.position_sizing == "score":
                    buy_candidates.sort(
                        key=lambda x: x[1].get("_score", 0), reverse=True
                    )

                available_slots = self.max_positions - len(positions)
                buy_candidates = buy_candidates[:available_slots]

                # 等權分配可用資金
                if buy_candidates:
                    per_position_capital = capital / len(buy_candidates)

                    for stock_id, row in buy_candidates:
                        price = row["close"]
                        avg_vol = row.get("_avg_vol_20", 0)
                        avg_vol = avg_vol if pd.notna(avg_vol) else 0

                        slip = self._get_slippage(0, avg_vol)  # 初始估計
                        buy_price = price * (1 + slip)
                        buy_cost = buy_price * (1 + self.commission)

                        shares = (
                            int(per_position_capital / buy_cost / 1000) * 1000
                        )

                        # 流動性限制
                        if self.max_participation < 1.0 and avg_vol > 0:
                            max_shares = (
                                int(avg_vol * self.max_participation / 1000)
                                * 1000
                            )
                            shares = min(shares, max_shares)
                        if (
                            self.min_avg_volume > 0
                            and avg_vol < self.min_avg_volume
                        ):
                            shares = 0

                        if shares > 0:
                            # 重算動態滑價（用實際 shares）
                            slip = self._get_slippage(shares, avg_vol)
                            buy_price = price * (1 + slip)
                            total_cost = (
                                shares * buy_price * (1 + self.commission)
                            )

                            if total_cost <= capital:
                                capital -= total_cost
                                positions[stock_id] = {
                                    "shares": shares,
                                    "entry_price": buy_price,
                                    "entry_date": date,
                                }

            # --- 計算當日權益 ---
            position_value = sum(
                pos["shares"] * daily_info[sid]["close"]
                for sid, pos in positions.items()
                if sid in daily_info
            )
            equity = capital + position_value
            equity_history.append({"date": date, "equity": equity})
            position_count_history.append(len(positions))

        # Step 4: 計算績效
        equity_df = pd.DataFrame(equity_history)
        if equity_df.empty:
            return MultiStockResult()

        equity_series = pd.Series(
            equity_df["equity"].values, index=equity_df["date"]
        )
        trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()

        return self._calc_metrics(
            equity_series, trades_df, position_count_history
        )

    def _get_slippage(self, shares: int, avg_volume: float) -> float:
        """計算滑價（支援動態滑價）"""
        if self.dynamic_slippage and avg_volume > 0:
            base = 0.0005
            participation = shares / avg_volume if avg_volume > 0 else 0
            impact = participation * self.impact_coeff
            return base + impact
        return self.slippage

    def _calc_metrics(
        self,
        equity: pd.Series,
        trades: pd.DataFrame,
        position_counts: list[int],
    ) -> MultiStockResult:
        """計算組合績效指標"""
        if equity.empty:
            return MultiStockResult()

        returns = equity.pct_change().dropna()
        total_return = (equity.iloc[-1] / self.initial_capital) - 1

        days = (equity.index[-1] - equity.index[0]).days
        annual_return = (
            (1 + total_return) ** (365 / days) - 1 if days > 0 else 0.0
        )

        rf = RISK_FREE_RATE
        if len(returns) > 1 and returns.std() > _EPS:
            sharpe = (
                (returns.mean() - rf / TRADING_DAYS_PER_YEAR)
                / returns.std()
                * np.sqrt(TRADING_DAYS_PER_YEAR)
            )
        else:
            sharpe = 0.0

        downside = returns[returns < 0]
        if len(downside) > 1 and downside.std() > _EPS:
            sortino = (
                (returns.mean() - rf / TRADING_DAYS_PER_YEAR)
                / downside.std()
                * np.sqrt(TRADING_DAYS_PER_YEAR)
            )
        else:
            sortino = 0.0

        peak = equity.cummax()
        drawdown = (equity - peak) / peak
        max_drawdown = drawdown.min()

        trade_count = len(trades)
        if trade_count > 0:
            wins = trades[trades["pnl"] > 0]
            losses = trades[trades["pnl"] <= 0]
            win_rate = len(wins) / trade_count
            total_profit = wins["pnl"].sum() if not wins.empty else 0
            total_loss = abs(losses["pnl"].sum()) if not losses.empty else 0
            profit_factor = (
                total_profit / total_loss if total_loss > _EPS else 999.0
            )
            avg_holding = trades["holding_days"].mean()
        else:
            win_rate = 0.0
            profit_factor = 0.0
            avg_holding = 0.0

        max_concurrent = max(position_counts) if position_counts else 0
        avg_concurrent = (
            sum(position_counts) / len(position_counts)
            if position_counts
            else 0
        )

        # 月報酬（需 DatetimeIndex 才能 resample）
        if len(returns) > 20:
            eq_dt = equity.copy()
            eq_dt.index = pd.to_datetime(eq_dt.index)
            monthly = eq_dt.resample("ME").last().pct_change().dropna()
        else:
            monthly = pd.Series(dtype=float)

        # 年化換手率 = 交易次數 × 2 / 平均持股數 / 年數
        years = days / 365 if days > 0 else 1
        turnover = (
            (trade_count * 2) / max(avg_concurrent, 1) / years
            if years > 0
            else 0
        )

        # 分年績效
        annual_rows = self._calc_annual_breakdown(equity, trades, rf)

        return MultiStockResult(
            total_return=round(total_return, 4),
            annual_return=round(annual_return, 4),
            sharpe_ratio=round(sharpe, 2),
            sortino_ratio=round(sortino, 2),
            max_drawdown=round(max_drawdown, 4),
            win_rate=round(win_rate, 4),
            profit_factor=round(profit_factor, 2),
            trade_count=trade_count,
            avg_holding_days=round(avg_holding, 1),
            max_concurrent_positions=max_concurrent,
            avg_concurrent_positions=round(avg_concurrent, 1),
            turnover_rate=round(turnover, 2),
            equity_curve=equity,
            drawdown_curve=drawdown,
            trades=trades,
            monthly_returns=monthly,
            annual_breakdown=pd.DataFrame(annual_rows),
        )

    def _calc_annual_breakdown(
        self,
        equity: pd.Series,
        trades: pd.DataFrame,
        rf: float,
    ) -> list[dict]:
        """按年度拆解績效"""
        annual_rows: list[dict] = []
        for year in sorted(set(d.year for d in equity.index)):
            yr_eq = equity[
                equity.index.map(lambda d, y=year: d.year == y)
            ]
            if len(yr_eq) < 2:
                continue
            yr_ret = yr_eq.iloc[-1] / yr_eq.iloc[0] - 1
            yr_returns = yr_eq.pct_change().dropna()
            yr_sharpe = 0.0
            if len(yr_returns) > 1 and yr_returns.std() > _EPS:
                yr_sharpe = (
                    (yr_returns.mean() - rf / TRADING_DAYS_PER_YEAR)
                    / yr_returns.std()
                    * np.sqrt(TRADING_DAYS_PER_YEAR)
                )
            yr_peak = yr_eq.cummax()
            yr_mdd = ((yr_eq - yr_peak) / yr_peak).min()

            yr_trades_count = 0
            yr_win_rate = 0.0
            if not trades.empty and "entry_date" in trades.columns:
                yr_t = trades[
                    trades["entry_date"].apply(
                        lambda d, y=year: (
                            d.year == y if hasattr(d, "year") else False
                        )
                    )
                ]
                yr_trades_count = len(yr_t)
                yr_win_rate = (
                    len(yr_t[yr_t["pnl"] > 0]) / yr_trades_count
                    if yr_trades_count > 0
                    else 0
                )

            annual_rows.append({
                "year": year,
                "return": round(yr_ret, 4),
                "sharpe": round(yr_sharpe, 2),
                "max_drawdown": round(yr_mdd, 4),
                "trade_count": yr_trades_count,
                "win_rate": round(yr_win_rate, 4),
            })
        return annual_rows
