"""MACD 訊號策略 — MACD 柱狀連續確認 + 趨勢過濾"""

import pandas as pd

from analysis.strategies.base import Strategy
from analysis.utils.indicators import _ema, _sma


class MACDStrategy(Strategy):
    name = "MACD 訊號"
    description = "MACD 柱狀圖連續正值確認買入，連續負值確認賣出（+ 趨勢過濾）"
    params = {"fast": 12, "slow": 26, "signal": 9, "confirm_bars": 2, "trend_period": 100}

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        ema_fast = _ema(df["close"], self.params["fast"])
        ema_slow = _ema(df["close"], self.params["slow"])
        macd_line = ema_fast - ema_slow
        signal_line = _ema(macd_line, self.params["signal"])
        df["MACD_hist"] = macd_line - signal_line

        confirm = self.params.get("confirm_bars", 2)
        trend_p = self.params.get("trend_period", 100)

        # 連續確認：柱狀圖需連續 confirm_bars 根為正/負
        hist_positive = (df["MACD_hist"] > 0).astype(float)
        hist_negative = (df["MACD_hist"] < 0).astype(float)
        consecutive_pos = hist_positive.rolling(confirm, min_periods=confirm).min()
        consecutive_neg = hist_negative.rolling(confirm, min_periods=confirm).min()

        buy_sig = (consecutive_pos == 1) & (consecutive_pos.shift(1) < 1)
        sell_sig = (consecutive_neg == 1) & (consecutive_neg.shift(1) < 1)

        # 趨勢過濾
        ma_trend = _sma(df["close"], trend_p)
        in_uptrend = df["close"] > ma_trend
        buy_sig = buy_sig & in_uptrend

        df["signal"] = 0
        df.loc[buy_sig, "signal"] = 1
        df.loc[sell_sig, "signal"] = -1

        return df
