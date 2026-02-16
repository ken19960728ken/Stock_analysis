"""Heikin-Ashi 策略 — HA K 線型態轉換進出場"""

import numpy as np
import pandas as pd

from analysis.strategies.base import Strategy


class HeikinAshiStrategy(Strategy):
    name = "Heikin-Ashi"
    description = "HA K 線由陰轉陽買入，由陽轉陰賣出（搭配連續確認）"
    params = {"confirm_bars": 2}

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()

        # 計算 Heikin-Ashi
        ha_close = (df["open"] + df["high"] + df["low"] + df["close"]) / 4
        ha_open = pd.Series(np.nan, index=df.index)
        ha_open.iloc[0] = (df["open"].iloc[0] + df["close"].iloc[0]) / 2
        for i in range(1, len(df)):
            ha_open.iloc[i] = (ha_open.iloc[i - 1] + ha_close.iloc[i - 1]) / 2

        df["signal"] = 0

        bullish = (ha_close > ha_open)
        bearish = (ha_close < ha_open)

        confirm = self.params["confirm_bars"]
        if confirm <= 1:
            df.loc[bullish & bearish.shift(1), "signal"] = 1
            df.loc[bearish & bullish.shift(1), "signal"] = -1
        else:
            consecutive_bull = bullish.astype(int)
            consecutive_bear = bearish.astype(int)
            for i in range(1, confirm):
                consecutive_bull = consecutive_bull + bullish.shift(i).fillna(False).astype(int)
                consecutive_bear = consecutive_bear + bearish.shift(i).fillna(False).astype(int)

            df.loc[
                (consecutive_bull >= confirm) &
                (consecutive_bull.shift(1) < confirm),
                "signal"
            ] = 1
            df.loc[
                (consecutive_bear >= confirm) &
                (consecutive_bear.shift(1) < confirm),
                "signal"
            ] = -1

        return df
