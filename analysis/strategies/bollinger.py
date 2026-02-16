"""Bollinger Bands 突破策略 — 觸下軌買入，觸上軌賣出"""

import pandas as pd

from analysis.strategies.base import Strategy
from analysis.utils.indicators import _sma


class BollingerStrategy(Strategy):
    name = "Bollinger 突破"
    description = "價格觸及下軌買入，觸及上軌賣出"
    params = {"period": 20, "std_dev": 2.0}

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        period = self.params["period"]
        std_dev = self.params["std_dev"]

        mid = _sma(df["close"], period)
        rolling_std = df["close"].rolling(window=period, min_periods=period).std()
        df["BB_lower"] = mid - std_dev * rolling_std
        df["BB_upper"] = mid + std_dev * rolling_std

        df["signal"] = 0
        df.loc[
            (df["close"] <= df["BB_lower"]) &
            (df["close"].shift(1) > df["BB_lower"].shift(1)),
            "signal"
        ] = 1
        df.loc[
            (df["close"] >= df["BB_upper"]) &
            (df["close"].shift(1) < df["BB_upper"].shift(1)),
            "signal"
        ] = -1

        return df
