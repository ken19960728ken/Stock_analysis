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
        "buy_threshold": 0.4,
        "sell_threshold": -0.2,
        "use_zscore": False,
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

        # MA 方向（增加 MA 趨勢權重）
        ma20 = _sma(df["close"], 20)
        above_ma = (df["close"] > ma20).astype(float) * 2 - 1
        tech_score = tech_score + above_ma

        # MA 趨勢方向加分（MA20 向上 +1, 向下 -1）
        ma20_direction = (ma20 > ma20.shift(5)).astype(float) * 2 - 1
        tech_score = tech_score + ma20_direction

        # 正規化到 [-1, 1]（使用 expanding max 避免 look-ahead bias）
        tech_max = tech_score.abs().expanding(min_periods=1).max()
        tech_score = tech_score / tech_max.replace(0, 1)

        # --- 籌碼面分數 ---
        chip_score = pd.Series(0.0, index=df.index)
        buy_col = None
        # 優先匹配淨買超欄位
        if "institutional_net_buy" in df.columns:
            buy_col = "institutional_net_buy"
        else:
            for col in df.columns:
                cl = col.lower()
                if "net" in cl and any(k in cl for k in ["buy", "買", "foreign", "institutional"]):
                    buy_col = col
                    break
        if buy_col is not None:
            vals = pd.to_numeric(df[buy_col], errors="coerce").fillna(0)
            chip_score = vals.apply(lambda x: 1.0 if x > 0 else (-1.0 if x < 0 else 0.0))

        # --- 基本面分數 ---
        fund_score = pd.Series(0.0, index=df.index)
        pe_col = None
        for c in df.columns:
            cl = c.lower()
            if c == "PER" or cl in ("per", "pe_ratio", "pe", "本益比") or "p/e" in cl:
                pe_col = c
                break
        if pe_col is not None:
            pe = pd.to_numeric(df[pe_col], errors="coerce")
            fund_score = pe.apply(lambda x: 1.0 if 0 < x < 15 else (-0.5 if x > 30 else 0.0))

        # --- Z-Score 標準化（可選） ---
        if self.params.get("use_zscore", False):
            from analysis.utils.factor_engine import zscore_normalize
            tech_score = zscore_normalize(tech_score)
            chip_score = zscore_normalize(chip_score)
            fund_score = zscore_normalize(fund_score)

        # --- 綜合評分（權重正規化） ---
        w = self.params
        w_sum = w["tech_weight"] + w["chip_weight"] + w["fund_weight"]
        w_sum = w_sum if w_sum > 0 else 1.0
        total_score = (
            tech_score * (w["tech_weight"] / w_sum)
            + chip_score * (w["chip_weight"] / w_sum)
            + fund_score * (w["fund_weight"] / w_sum)
        )

        buy_sig = (total_score > w["buy_threshold"]) & (total_score.shift(1) <= w["buy_threshold"])
        sell_sig = (total_score < w["sell_threshold"]) & (total_score.shift(1) >= w["sell_threshold"])
        df.loc[buy_sig, "signal"] = 1
        df.loc[sell_sig, "signal"] = -1

        return df
