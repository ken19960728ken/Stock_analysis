"""Dual Thrust 策略 — 開盤區間突破 + 成交量確認"""

import pandas as pd

from analysis.strategies.base import Strategy


class DualThrustStrategy(Strategy):
    name = "Dual Thrust"
    description = "基於前 N 日高低點計算上下軌，突破上軌+量確認買入，跌破下軌賣出"
    params = {"lookback": 5, "k1": 0.7, "k2": 0.7, "volume_ratio": 1.2}

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        n = self.params["lookback"]
        k1 = self.params["k1"]
        k2 = self.params["k2"]
        vol_ratio = self.params.get("volume_ratio", 1.2)

        # 計算 Range（排除當日，避免 Look-Ahead Bias）
        hh = df["high"].shift(1).rolling(n).max()  # 前 N 日最高價
        lc = df["close"].shift(1).rolling(n).min()  # 前 N 日最低收盤
        hc = df["close"].shift(1).rolling(n).max()  # 前 N 日最高收盤
        ll = df["low"].shift(1).rolling(n).min()  # 前 N 日最低價

        range_val = pd.concat([hh - lc, hc - ll], axis=1).max(axis=1)

        # 上下軌
        df["upper"] = df["open"] + k1 * range_val
        df["lower"] = df["open"] - k2 * range_val

        # 成交量確認：突破時成交量需 > 20日均量 × volume_ratio
        vol_ma = df["volume"].rolling(20, min_periods=1).mean()
        vol_confirm = df["volume"] > vol_ma * vol_ratio

        df["signal"] = 0
        # 突破上軌 + 量確認 → 買入
        df.loc[
            (df["close"] > df["upper"]) &
            (df["close"].shift(1) <= df["upper"].shift(1)) &
            vol_confirm,
            "signal"
        ] = 1
        # 跌破下軌 → 賣出
        df.loc[
            (df["close"] < df["lower"]) &
            (df["close"].shift(1) >= df["lower"].shift(1)),
            "signal"
        ] = -1

        return df
