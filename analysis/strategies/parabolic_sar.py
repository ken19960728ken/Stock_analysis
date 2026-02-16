"""Parabolic SAR 策略 — SAR 翻多買入，翻空賣出"""

import numpy as np
import pandas as pd

from analysis.strategies.base import Strategy


class ParabolicSARStrategy(Strategy):
    name = "Parabolic SAR"
    description = "SAR 由上方翻到下方（翻多）買入，由下方翻到上方（翻空）賣出"
    params = {"af": 0.02, "max_af": 0.2}

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        af_init = self.params["af"]
        max_af = self.params["max_af"]

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
        df.loc[bull_signal, "signal"] = 1
        df.loc[bear_signal, "signal"] = -1

        return df
