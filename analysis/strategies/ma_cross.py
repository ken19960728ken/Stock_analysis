"""MA 交叉策略 — 短期均線上穿長期均線買入 + MA200 趨勢過濾"""

import pandas as pd

from analysis.strategies.base import Strategy
from analysis.utils.indicators import _sma


class MACrossStrategy(Strategy):
    name = "MA 交叉"
    description = "短期均線上穿長期均線買入，下穿賣出（+ MA 趨勢過濾）"
    params = {"fast_period": 10, "slow_period": 40, "trend_period": 200}

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        fast = self.params["fast_period"]
        slow = self.params["slow_period"]
        trend_p = self.params.get("trend_period", 200)

        df["fast_ma"] = _sma(df["close"], fast)
        df["slow_ma"] = _sma(df["close"], slow)
        trend_ma = _sma(df["close"], trend_p)

        # 趨勢過濾：只在 close > MA trend_period 時觸發金叉買入
        in_uptrend = df["close"] > trend_ma

        df["signal"] = 0
        df.loc[
            (df["fast_ma"] > df["slow_ma"]) &
            (df["fast_ma"].shift(1) <= df["slow_ma"].shift(1)) &
            in_uptrend,
            "signal"
        ] = 1
        df.loc[
            (df["fast_ma"] < df["slow_ma"]) &
            (df["fast_ma"].shift(1) >= df["slow_ma"].shift(1)),
            "signal"
        ] = -1

        return df
