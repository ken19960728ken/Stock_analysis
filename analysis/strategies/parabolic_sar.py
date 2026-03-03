"""Parabolic SAR 策略 — SAR 翻多買入，翻空賣出 + ADX 趨勢強度過濾"""

import numpy as np
import pandas as pd

from analysis.strategies.base import Strategy


class ParabolicSARStrategy(Strategy):
    name = "Parabolic SAR"
    description = "SAR 由上方翻到下方（翻多）買入，由下方翻到上方（翻空）賣出（+ ADX 過濾）"
    params = {"af": 0.02, "max_af": 0.2, "adx_period": 14, "adx_threshold": 25}

    def _calc_adx(self, df: pd.DataFrame, period: int) -> pd.Series:
        """計算 ADX 指標"""
        high = df["high"]
        low = df["low"]
        close = df["close"]

        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        plus_di = 100 * plus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr.replace(0, np.nan)
        minus_di = 100 * minus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr.replace(0, np.nan)

        dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
        adx = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        return adx

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        af_init = self.params["af"]
        max_af = self.params["max_af"]
        adx_period = self.params.get("adx_period", 14)
        adx_threshold = self.params.get("adx_threshold", 25)

        high = df["high"].values
        low = df["low"].values
        n = len(high)

        df["signal"] = 0
        if n < 2:
            return df

        sar_long = np.full(n, np.nan)
        sar_short = np.full(n, np.nan)

        bull = True
        af = af_init
        ep = high[0]
        sar_val = low[0]

        for i in range(1, n):
            if bull:
                sar_val = sar_val + af * (ep - sar_val)
                sar_val = min(sar_val, low[i - 1])
                if i >= 2:
                    sar_val = min(sar_val, low[i - 2])
                if low[i] < sar_val:
                    bull = False
                    sar_val = ep
                    ep = low[i]
                    af = af_init
                else:
                    if high[i] > ep:
                        ep = high[i]
                        af = min(af + af_init, max_af)
            else:
                sar_val = sar_val + af * (ep - sar_val)
                sar_val = max(sar_val, high[i - 1])
                if i >= 2:
                    sar_val = max(sar_val, high[i - 2])
                if high[i] > sar_val:
                    bull = True
                    sar_val = ep
                    ep = high[i]
                    af = af_init
                else:
                    if low[i] < ep:
                        ep = low[i]
                        af = min(af + af_init, max_af)

            if bull:
                sar_long[i] = sar_val
            else:
                sar_short[i] = sar_val

        sar_long_s = pd.Series(sar_long, index=df.index)
        sar_short_s = pd.Series(sar_short, index=df.index)

        # 從空翻多: sar_long 從 NaN 變有值
        bull_signal = sar_long_s.notna() & sar_long_s.shift(1).isna()
        bear_signal = sar_short_s.notna() & sar_short_s.shift(1).isna()

        # ADX 趨勢強度過濾：只在趨勢明確時交易
        adx = self._calc_adx(df, adx_period)
        strong_trend = adx > adx_threshold

        df.loc[bull_signal & strong_trend, "signal"] = 1
        df.loc[bear_signal & strong_trend, "signal"] = -1

        return df
