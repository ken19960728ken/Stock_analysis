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

        # 簡化邏輯：RSI + MACD + 成交量的組合訊號
        df["signal"] = 0
        if len(df) < 30:
            return df

        # RSI
        delta = df["close"].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - 100 / (1 + rs)

        # MACD
        ema12 = df["close"].ewm(span=12).mean()
        ema26 = df["close"].ewm(span=26).mean()
        macd_hist = (ema12 - ema26) - (ema12 - ema26).ewm(span=9).mean()

        # 成交量比
        vol_ratio = df["volume"] / df["volume"].rolling(20).mean()

        # 綜合分數
        score = pd.Series(0.0, index=df.index)
        score += (rsi < 30).astype(float) * 0.4
        score += (macd_hist > 0).astype(float) * 0.3
        score += (vol_ratio > 1.5).astype(float) * 0.3
        score -= (rsi > 70).astype(float) * 0.4
        score -= (macd_hist < 0).astype(float) * 0.3

        df.loc[score >= 0.6, "signal"] = 1
        df.loc[score <= -0.4, "signal"] = -1

        return df
