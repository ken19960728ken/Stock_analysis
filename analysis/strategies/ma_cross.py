"""MA 交叉策略 — MA5 上穿 MA20 買入，下穿賣出"""

import pandas as pd

from analysis.strategies.base import Strategy
from analysis.utils.indicators import _sma


class MACrossStrategy(Strategy):
    name = "MA 交叉"
    description = "短期均線上穿長期均線買入，下穿賣出"
    params = {"fast_period": 5, "slow_period": 20}

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        fast = self.params["fast_period"]
        slow = self.params["slow_period"]

        df["fast_ma"] = _sma(df["close"], fast)
        df["slow_ma"] = _sma(df["close"], slow)

        df["signal"] = 0
        df.loc[
            (df["fast_ma"] > df["slow_ma"]) &
            (df["fast_ma"].shift(1) <= df["slow_ma"].shift(1)),
            "signal"
        ] = 1
        df.loc[
            (df["fast_ma"] < df["slow_ma"]) &
            (df["fast_ma"].shift(1) >= df["slow_ma"].shift(1)),
            "signal"
        ] = -1

        return df
