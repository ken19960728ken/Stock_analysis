"""MACD 訊號策略 — MACD 柱狀翻正買入，翻負賣出"""

import pandas as pd

from analysis.strategies.base import Strategy
from analysis.utils.indicators import _ema


class MACDStrategy(Strategy):
    name = "MACD 訊號"
    description = "MACD 柱狀圖由負轉正買入，由正轉負賣出"
    params = {"fast": 12, "slow": 26, "signal": 9}

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        ema_fast = _ema(df["close"], self.params["fast"])
        ema_slow = _ema(df["close"], self.params["slow"])
        macd_line = ema_fast - ema_slow
        signal_line = _ema(macd_line, self.params["signal"])
        df["MACD_hist"] = macd_line - signal_line

        df["signal"] = 0
        df.loc[
            (df["MACD_hist"] > 0) & (df["MACD_hist"].shift(1) <= 0),
            "signal"
        ] = 1
        df.loc[
            (df["MACD_hist"] < 0) & (df["MACD_hist"].shift(1) >= 0),
            "signal"
        ] = -1

        return df
