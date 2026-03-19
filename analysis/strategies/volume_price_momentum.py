"""量價動能策略 — 放量突破 + OBV 資金流向確認"""

import numpy as np
import pandas as pd

from analysis.strategies.base import Strategy
from analysis.utils.indicators import _sma, _ema, add_obv


class VolumePriceMomentumStrategy(Strategy):
    name = "量價動能"
    description = "放量突破前高 + OBV 資金流入 + 均線趨勢過濾"
    params = {
        "volume_multiple": 2.5,       # 放量倍數（2.0→2.5 減少假突破）
        "breakout_period": 20,        # 突破回顧期
        "obv_lookback": 5,            # OBV 斜率計算期
        "trend_period": 60,           # 趨勢均線期數
        "exit_ma_period": 20,         # 出場均線（10→20 減少被洗出）
        "shrink_days": 5,             # 量能萎縮天數（3→5 更寬容）
        "confirm_days": 2,            # 突破確認天數（新增）
    }

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        vol_mult = self.params["volume_multiple"]
        bp = self.params["breakout_period"]
        obv_lb = self.params["obv_lookback"]
        trend_p = self.params["trend_period"]
        exit_ma_p = self.params["exit_ma_period"]
        shrink_days = self.params["shrink_days"]
        confirm_days = self.params["confirm_days"]

        # 指標計算
        df = add_obv(df)
        df["vol_ma20"] = _sma(df["volume"], 20)
        df["high_max"] = df["close"].rolling(window=bp, min_periods=bp).max().shift(1)
        df["trend_ma"] = _sma(df["close"], trend_p)
        df["exit_ma"] = _sma(df["close"], exit_ma_p)

        # OBV 線性迴歸斜率（近 obv_lookback 日）
        obv_slope = df["OBV"].rolling(window=obv_lb, min_periods=obv_lb).apply(
            lambda x: np.polyfit(range(len(x)), x, 1)[0] if len(x) == obv_lb else 0,
            raw=False,
        )

        # 量能萎縮：連續 N 日量 < 20日均量
        vol_below = (df["volume"] < df["vol_ma20"]).astype(int)
        consec_shrink = vol_below.rolling(window=shrink_days, min_periods=shrink_days).sum()

        # ─── 突破確認：連續 confirm_days 日收在前高之上 ───
        above_high = (df["close"] > df["high_max"]).astype(int)
        confirmed_breakout = above_high.rolling(
            window=confirm_days, min_periods=confirm_days
        ).min() == 1

        # ─── 放量確認：近 confirm_days 日至少 1 天放量 ───
        vol_spike = (df["volume"] >= df["vol_ma20"] * vol_mult).astype(int)
        recent_vol_spike = vol_spike.rolling(
            window=confirm_days, min_periods=1
        ).max() == 1

        # 買入條件（更嚴格：需連續站穩 + 近期放量 + OBV 正斜率 + 均線之上）
        buy = (
            confirmed_breakout &
            recent_vol_spike &
            (obv_slope > 0) &
            (df["close"] > df["trend_ma"])
        )

        # 賣出條件：跌破均線，或量縮 + 價格回落至突破點以下
        sell = (
            (df["close"] < df["exit_ma"]) |
            ((consec_shrink >= shrink_days) & (df["close"] < df["high_max"]))
        )

        df["signal"] = 0
        df.loc[buy, "signal"] = 1
        df.loc[sell, "signal"] = -1

        return df
