"""RSI 反轉策略 — RSI < 30 買入，RSI > 70 賣出"""

import numpy as np
import pandas as pd

from analysis.strategies.base import Strategy


class RSIReversalStrategy(Strategy):
    name = "RSI 反轉"
    description = "RSI 超賣區買入，超買區賣出"
    params = {"period": 14, "oversold": 30, "overbought": 70}

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        period = self.params["period"]

        delta = df["close"].diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        df["RSI"] = 100 - (100 / (1 + rs))

        df["signal"] = 0
        df.loc[
            (df["RSI"] < self.params["oversold"]) &
            (df["RSI"].shift(1) >= self.params["oversold"]),
            "signal"
        ] = 1
        df.loc[
            (df["RSI"] > self.params["overbought"]) &
            (df["RSI"].shift(1) <= self.params["overbought"]),
            "signal"
        ] = -1

        return df
