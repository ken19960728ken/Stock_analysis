"""
機器學習選股策略 — 利用 LightGBM 多因子預測產生交易訊號
"""

import numpy as np
import pandas as pd

from analysis.strategies.base import Strategy


class MLFactorStrategy(Strategy):
    name = "機器學習選股"
    description = "利用 LightGBM 對多因子進行非線性組合，預測前瞻報酬分位"
    params = {
        "forward_days": 5,
        "buy_quantile": 2,
        "sell_quantile": 0,
    }

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        如果 data 已有 'pred_label' 欄位（由 ml_stock_picker 注入），直接使用。
        否則使用簡化的技術面因子做預測。
        """
        df = data.copy()

        if "pred_label" in df.columns:
            buy_q = self.params.get("buy_quantile", 2)
            sell_q = self.params.get("sell_quantile", 0)
            df["signal"] = 0
            df.loc[df["pred_label"] == buy_q, "signal"] = 1
            df.loc[df["pred_label"] == sell_q, "signal"] = -1
            return df

        # 簡化邏輯：RSI + MACD + 成交量的連續分數組合
        df["signal"] = 0
        if len(df) < 30:
            return df

        # RSI — Wilder smoothing（與 indicators.py 一致）
        delta = df["close"].diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - 100 / (1 + rs)

        # MACD
        ema12 = df["close"].ewm(span=12, adjust=False).mean()
        ema26 = df["close"].ewm(span=26, adjust=False).mean()
        macd_hist = (ema12 - ema26) - (ema12 - ema26).ewm(span=9, adjust=False).mean()

        # 成交量比
        vol_ratio = df["volume"] / df["volume"].rolling(20).mean()

        # 連續分數（非二元），消除因子間矛盾
        score = pd.Series(0.0, index=df.index)
        score += ((50 - rsi) / 50).clip(-1, 1) * 0.4
        score += np.sign(macd_hist) * 0.3
        score += (vol_ratio - 1).clip(-1, 1) * 0.3

        # 邊緣觸發：只在分數跨越閾值時產生訊號
        above = score >= 0.3
        below = score <= -0.3
        df.loc[above & ~above.shift(1, fill_value=False), "signal"] = 1
        df.loc[below & ~below.shift(1, fill_value=False), "signal"] = -1

        return df
