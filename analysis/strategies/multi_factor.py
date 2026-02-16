"""多因子綜合策略 — 技術面 + 籌碼面 + 基本面加權評分"""

import numpy as np
import pandas as pd

from analysis.strategies.base import Strategy
from analysis.utils.indicators import _ema, _sma


class MultiFactorStrategy(Strategy):
    name = "多因子綜合"
    description = "綜合技術面(RSI/MACD)、籌碼面(法人)、基本面(PER) 加權評分"
    params = {
        "tech_weight": 0.4,
        "chip_weight": 0.3,
        "fund_weight": 0.3,
        "buy_threshold": 0.6,
        "sell_threshold": -0.3,
    }

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["signal"] = 0

        # --- 技術面分數 ---
        tech_score = pd.Series(0.0, index=df.index)

        # RSI
        delta = df["close"].diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        tech_score = tech_score.add(
            rsi.apply(lambda x: 1.0 if x < 30 else (-1.0 if x > 70 else 0.0)),
            fill_value=0,
        )

        # MACD
        ema12 = _ema(df["close"], 12)
        ema26 = _ema(df["close"], 26)
        macd_line = ema12 - ema26
        signal_line = _ema(macd_line, 9)
        hist = macd_line - signal_line
        tech_score = tech_score.add(
            hist.apply(lambda x: 1.0 if x > 0 else -1.0 if x < 0 else 0.0),
            fill_value=0,
        )

        # MA 方向
        ma20 = _sma(df["close"], 20)
        above_ma = (df["close"] > ma20).astype(float) * 2 - 1
        tech_score = tech_score + above_ma

        # 正規化到 [-1, 1]
        tech_max = tech_score.abs().max()
        if tech_max > 0:
            tech_score = tech_score / tech_max

        # --- 籌碼面分數 ---
        chip_score = pd.Series(0.0, index=df.index)
        buy_col = None
        for col in df.columns:
            if any(k in col.lower() for k in ["buy", "買", "foreign", "institutional"]):
                buy_col = col
                break
        if buy_col is not None:
            vals = pd.to_numeric(df[buy_col], errors="coerce").fillna(0)
            chip_score = vals.apply(lambda x: 1.0 if x > 0 else (-1.0 if x < 0 else 0.0))

        # --- 基本面分數 ---
        fund_score = pd.Series(0.0, index=df.index)
        pe_col = None
        for c in df.columns:
            if "PER" in c or "pe" in c.lower():
                pe_col = c
                break
        if pe_col is not None:
            pe = pd.to_numeric(df[pe_col], errors="coerce")
            fund_score = pe.apply(lambda x: 1.0 if 0 < x < 15 else (-0.5 if x > 30 else 0.0))

        # --- 綜合評分 ---
        w = self.params
        total_score = (
            tech_score * w["tech_weight"]
            + chip_score * w["chip_weight"]
            + fund_score * w["fund_weight"]
        )

        buy_sig = (total_score > w["buy_threshold"]) & (total_score.shift(1) <= w["buy_threshold"])
        sell_sig = (total_score < w["sell_threshold"]) & (total_score.shift(1) >= w["sell_threshold"])
        df.loc[buy_sig, "signal"] = 1
        df.loc[sell_sig, "signal"] = -1

        return df
