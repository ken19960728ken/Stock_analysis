"""波動率壓縮突破策略 — Bollinger Band + Keltner Channel Squeeze"""

import pandas as pd

from analysis.strategies.base import Strategy
from analysis.utils.indicators import _sma, _ema, add_bollinger, add_keltner, add_rsi


class VolatilitySqueezeStrategy(Strategy):
    name = "波動率壓縮突破"
    description = "BB 收窄進入 KC 後放大突破 + RSI 動量確認"
    params = {
        "bb_period": 20,
        "bb_std": 2.0,
        "kc_period": 20,
        "kc_mult": 1.5,
        "atr_period": 14,
        "squeeze_min_days": 5,        # 壓縮最少持續天數（新增，避免假壓縮）
        "rsi_threshold": 50,
        "exit_ema_period": 20,        # 出場 EMA 期數（取代 BB_mid）
        "trend_period": 60,           # 趨勢過濾均線（新增）
        "atr_stop_multiple": 2.0,
    }

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        bb_p = self.params["bb_period"]
        bb_std = self.params["bb_std"]
        kc_p = self.params["kc_period"]
        kc_mult = self.params["kc_mult"]
        atr_p = self.params["atr_period"]
        rsi_thr = self.params["rsi_threshold"]
        squeeze_min = self.params["squeeze_min_days"]
        exit_ema_p = self.params["exit_ema_period"]
        trend_p = self.params["trend_period"]

        # 計算指標
        df = add_bollinger(df, period=bb_p, std_dev=bb_std)
        df = add_keltner(df, period=kc_p, atr_mult=kc_mult, atr_period=atr_p)
        df = add_rsi(df, period=14)

        # ATR（用於追蹤停損）
        high_low = df["high"] - df["low"]
        high_pc = (df["high"] - df["close"].shift(1)).abs()
        low_pc = (df["low"] - df["close"].shift(1)).abs()
        tr = pd.concat([high_low, high_pc, low_pc], axis=1).max(axis=1)
        df["_ATR"] = tr.ewm(alpha=1 / atr_p, min_periods=atr_p, adjust=False).mean()

        # 輔助指標
        df["_vol_ma20"] = _sma(df["volume"], 20)
        df["_exit_ema"] = _ema(df["close"], exit_ema_p)
        df["_trend_ma"] = _sma(df["close"], trend_p)

        # ─── Squeeze 判斷：BB 在 KC 內部 ───
        squeeze_on = (df["BB_upper"] < df["KC_upper"]) & (df["BB_lower"] > df["KC_lower"])
        squeeze_off = ~squeeze_on

        # ─── 壓縮持續天數：連續 squeeze_min 天以上才算有效壓縮 ───
        squeeze_int = squeeze_on.astype(int)
        squeeze_cumsum = squeeze_int.rolling(
            window=squeeze_min, min_periods=squeeze_min
        ).sum()
        sustained_squeeze = squeeze_cumsum >= squeeze_min

        # 前一日仍在持續壓縮，今日解除 → 有效突破
        prev_sustained = sustained_squeeze.shift(1, fill_value=False)

        # ─── 買入條件 ───
        buy = (
            prev_sustained &
            squeeze_off &
            (df["close"] > df["BB_upper"]) &
            (df["RSI"] > rsi_thr) &
            (df["volume"] > df["_vol_ma20"]) &
            (df["close"] > df["_trend_ma"])  # 大趨勢過濾
        )

        # ─── 賣出條件：跌破 EMA 或重新壓縮 ───
        sell = (
            (df["close"] < df["_exit_ema"]) |
            sustained_squeeze  # 重新進入持續壓縮
        )

        df["signal"] = 0
        df.loc[buy, "signal"] = 1
        df.loc[sell & ~buy, "signal"] = -1  # 買賣同 bar 時買入優先

        # 清理暫時欄位
        df.drop(
            columns=["_ATR", "_vol_ma20", "_exit_ema", "_trend_ma"],
            errors="ignore", inplace=True,
        )

        return df
