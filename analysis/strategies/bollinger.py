"""Bollinger Bands 均值回歸策略 — 觸下軌 + RSI 超賣買入，觸上軌 + RSI 超買賣出"""

import numpy as np
import pandas as pd

from analysis.strategies.base import Strategy
from analysis.utils.indicators import _sma


class BollingerStrategy(Strategy):
    name = "Bollinger 突破"
    description = "價格觸及下軌 + RSI 超賣確認買入，觸及上軌 + RSI 超買確認賣出"
    params = {"period": 20, "std_dev": 2.0, "rsi_oversold": 35, "rsi_overbought": 65}

    def _calc_rsi(self, close: pd.Series, period: int = 14) -> pd.Series:
        """計算 RSI"""
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        period = self.params["period"]
        std_dev = self.params["std_dev"]
        rsi_oversold = self.params.get("rsi_oversold", 35)
        rsi_overbought = self.params.get("rsi_overbought", 65)

        mid = _sma(df["close"], period)
        rolling_std = df["close"].rolling(window=period, min_periods=period).std()
        df["BB_lower"] = mid - std_dev * rolling_std
        df["BB_upper"] = mid + std_dev * rolling_std

        rsi = self._calc_rsi(df["close"])

        df["signal"] = 0
        # 買入：觸碰下軌 + RSI 超賣（真正超賣，非趨勢下跌）
        df.loc[
            (df["close"] <= df["BB_lower"]) &
            (df["close"].shift(1) > df["BB_lower"].shift(1)) &
            (rsi < rsi_oversold),
            "signal"
        ] = 1
        # 賣出：觸碰上軌 + RSI 超買
        df.loc[
            (df["close"] >= df["BB_upper"]) &
            (df["close"].shift(1) < df["BB_upper"].shift(1)) &
            (rsi > rsi_overbought),
            "signal"
        ] = -1

        return df
