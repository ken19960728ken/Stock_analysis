"""MACD 訊號策略 — MACD 柱狀連續確認 + 趨勢過濾 + 背離偵測"""

import numpy as np
import pandas as pd

from analysis.strategies.base import Strategy
from analysis.utils.indicators import _ema, _sma


class MACDStrategy(Strategy):
    name = "MACD 訊號"
    description = "MACD 柱狀圖連續確認 + 趨勢過濾 + Price/MACD 背離偵測"
    params = {
        "fast": 12, "slow": 26, "signal": 9,
        "confirm_bars": 2, "trend_period": 100,
        "use_divergence": True,
        "divergence_lookback": 30,
        "divergence_order": 5,
    }

    def _detect_divergence(self, df: pd.DataFrame, lookback: int, order: int):
        """偵測 Price vs MACD_hist 背離

        Returns (bullish_div, bearish_div) — 兩個 bool Series
        """
        n = len(df)
        bullish = pd.Series(False, index=df.index)
        bearish = pd.Series(False, index=df.index)

        if n < lookback or order < 1:
            return bullish, bearish

        close = df["close"].values
        hist = df["MACD_hist"].values

        # 用 numpy 找 local extrema（不依賴 scipy）
        def find_local_min(arr, order):
            """回傳 local minimum 的索引列表"""
            indices = []
            for i in range(order, len(arr) - order):
                if np.isnan(arr[i]):
                    continue
                is_min = True
                for j in range(1, order + 1):
                    if np.isnan(arr[i - j]) or np.isnan(arr[i + j]):
                        is_min = False
                        break
                    if arr[i] > arr[i - j] or arr[i] > arr[i + j]:
                        is_min = False
                        break
                if is_min:
                    indices.append(i)
            return indices

        def find_local_max(arr, order):
            """回傳 local maximum 的索引列表"""
            indices = []
            for i in range(order, len(arr) - order):
                if np.isnan(arr[i]):
                    continue
                is_max = True
                for j in range(1, order + 1):
                    if np.isnan(arr[i - j]) or np.isnan(arr[i + j]):
                        is_max = False
                        break
                    if arr[i] < arr[i - j] or arr[i] < arr[i + j]:
                        is_max = False
                        break
                if is_max:
                    indices.append(i)
            return indices

        # 在回溯視窗內尋找背離
        for i in range(lookback, n):
            window_start = i - lookback

            # 看漲背離：價格創新低但「同一時間點」的 MACD_hist 未創新低
            price_mins = find_local_min(close[window_start:i + 1], order)

            if len(price_mins) >= 2:
                # 比較價格的兩個低點，以及這兩個時間點對應的 MACD_hist
                p1, p2 = price_mins[-2], price_mins[-1]
                if (close[window_start + p2] < close[window_start + p1] and
                        hist[window_start + p2] > hist[window_start + p1]):
                    bullish.iloc[i] = True

            # 看跌背離：價格創新高但「同一時間點」的 MACD_hist 未創新高
            price_maxs = find_local_max(close[window_start:i + 1], order)

            if len(price_maxs) >= 2:
                p1, p2 = price_maxs[-2], price_maxs[-1]
                if (close[window_start + p2] > close[window_start + p1] and
                        hist[window_start + p2] < hist[window_start + p1]):
                    bearish.iloc[i] = True

        return bullish, bearish

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

        # 背離偵測
        if self.params.get("use_divergence", True):
            lookback = self.params.get("divergence_lookback", 30)
            order = self.params.get("divergence_order", 5)
            bullish_div, bearish_div = self._detect_divergence(df, lookback, order)
            # 看漲背離 + MACD_hist 翻正 → 額外買入
            div_buy = bullish_div & (df["MACD_hist"] > 0)
            # 看跌背離 + MACD_hist 翻負 → 額外賣出
            div_sell = bearish_div & (df["MACD_hist"] < 0)
            buy_sig = buy_sig | div_buy
            sell_sig = sell_sig | div_sell

        # 趨勢過濾（買入需在上升趨勢）
        ma_trend = _sma(df["close"], trend_p)
        in_uptrend = df["close"] > ma_trend
        buy_sig = buy_sig & in_uptrend

        df["signal"] = 0
        df.loc[buy_sig, "signal"] = 1
        df.loc[sell_sig, "signal"] = -1

        return df
