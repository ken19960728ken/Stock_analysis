"""Heikin-Ashi 策略 — HA K 線型態轉換進出場 + MA 趨勢過濾"""

import numpy as np
import pandas as pd

from analysis.strategies.base import Strategy


class HeikinAshiStrategy(Strategy):
    name = "Heikin-Ashi"
    description = "HA K 線由陰轉陽買入，由陽轉陰賣出（搭配連續確認 + MA 趨勢過濾）"
    params = {"confirm_bars": 3, "trend_period": 50}

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["signal"] = 0

        if len(df) < 2:
            return df

        # 計算 Heikin-Ashi
        ha_close = (df["open"] + df["high"] + df["low"] + df["close"]) / 4
        ha_open = pd.Series(np.nan, index=df.index)
        ha_open.iloc[0] = (df["open"].iloc[0] + df["close"].iloc[0]) / 2
        for i in range(1, len(df)):
            ha_open.iloc[i] = (ha_open.iloc[i - 1] + ha_close.iloc[i - 1]) / 2

        bullish = (ha_close > ha_open)
        bearish = (ha_close < ha_open)

        confirm = self.params["confirm_bars"]
        trend_period = self.params.get("trend_period", 50)

        # MA 趨勢過濾: 只在 close > MA trend_period 時做多
        ma_trend = df["close"].rolling(trend_period, min_periods=1).mean()
        in_uptrend = df["close"] > ma_trend

        if confirm <= 1:
            buy_sig = bullish & bearish.shift(1) & in_uptrend
            sell_sig = bearish & bullish.shift(1)
            df.loc[buy_sig, "signal"] = 1
            df.loc[sell_sig, "signal"] = -1
        else:
            # 真正連續確認：sliding window 全為 True 才算
            consecutive_bull = bullish.astype(float).rolling(confirm, min_periods=confirm).min()
            consecutive_bear = bearish.astype(float).rolling(confirm, min_periods=confirm).min()

            prev_bull = consecutive_bull.shift(1).fillna(0)
            prev_bear = consecutive_bear.shift(1).fillna(0)

            buy_sig = (
                (consecutive_bull == 1) &
                (prev_bull < 1) &
                in_uptrend
            )
            sell_sig = (
                (consecutive_bear == 1) &
                (prev_bear < 1)
            )
            df.loc[buy_sig, "signal"] = 1
            df.loc[sell_sig, "signal"] = -1

        return df
