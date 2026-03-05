"""RSI 反轉策略 — RSI 超賣買入 + 趨勢均線過濾 + 可選 ATR 波動過濾"""

import numpy as np
import pandas as pd

from analysis.strategies.base import Strategy
from analysis.utils.indicators import _sma, add_atr


class RSIReversalStrategy(Strategy):
    name = "RSI 反轉"
    description = "RSI 超賣區買入，超買區賣出（可選趨勢過濾 + ATR 過濾）"
    params = {
        "period": 14,
        "oversold": 30,
        "overbought": 70,
        "trend_period": 60,
        "use_trend_filter": True,
        "use_atr_filter": False,
        "atr_period": 14,
        "atr_threshold": 0.5,
    }

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        period = self.params["period"]

        delta = df["close"].diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        df["RSI"] = 100 - (100 / (1 + rs))

        # 基本 RSI 穿越訊號
        buy_cond = (
            (df["RSI"] < self.params["oversold"]) &
            (df["RSI"].shift(1) >= self.params["oversold"])
        )
        sell_cond = (
            (df["RSI"] > self.params["overbought"]) &
            (df["RSI"].shift(1) <= self.params["overbought"])
        )

        # 趨勢均線過濾（僅過濾買入，賣出不受影響）
        # 使用 MA 方向上升（而非 close > MA），因為 RSI 超賣時
        # close 幾乎一定低於中長期 MA，用 close > MA 會過度過濾
        if self.params.get("use_trend_filter", True):
            trend_p = self.params.get("trend_period", 60)
            trend_ma = _sma(df["close"], trend_p)
            trend_rising = trend_ma > trend_ma.shift(5)
            buy_cond = buy_cond & trend_rising

        # ATR 波動過濾（預設關閉）
        if self.params.get("use_atr_filter", False):
            atr_p = self.params.get("atr_period", 14)
            atr_thresh = self.params.get("atr_threshold", 0.5)
            df = add_atr(df, period=atr_p)
            atr_pct = df["ATR"] / df["close"] * 100
            buy_cond = buy_cond & (atr_pct > atr_thresh)

        df["signal"] = 0
        df.loc[buy_cond, "signal"] = 1
        df.loc[sell_cond, "signal"] = -1

        return df
