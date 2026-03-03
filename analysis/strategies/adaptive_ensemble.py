"""
多策略動態組合 — 結合法人跟單、價值投資、趨勢動能三大子策略

改進原理：
1. 法人跟單 (Sharpe 0.84)：風險調整報酬最佳，提供高品質的籌碼面訊號
2. 價值投資 (年化 +29.94%)：報酬最高但波動大，需要其他策略平衡風險
3. 趨勢動能（MA + MACD）：確認進場時機，避免在下跌趨勢中買入價值陷阱

組合邏輯：
- 三大子策略各自計算分數 [-1, +1]
- 加權組合後，總分超過閾值才觸發交易
- 要求至少 2 個子策略同意才進場（共識機制）
- 最低持有期間 15 天，減少過度交易

理論基礎：
- Ensemble methods (Breiman, 1996): 多個弱策略組合通常優於單一強策略
- 多維度確認：技術面趨勢 + 籌碼面資金流 + 基本面估值 三維度同時確認
  大幅降低假訊號（每個維度獨立犯錯的機率相乘）
- 台灣市場特性：法人動向對股價有高預測力（外資佔比約 40%），
  結合基本面篩選可避免追逐題材股
"""

import numpy as np
import pandas as pd

from analysis.strategies.base import Strategy
from analysis.utils.indicators import _ema, _sma


class AdaptiveEnsembleStrategy(Strategy):
    name = "多策略動態組合"
    description = "法人跟單 + 價值投資 + 趨勢動能 三維度共識組合"
    params = {
        # 子策略權重
        "institutional_weight": 0.40,    # 法人權重（Sharpe 最高）
        "value_weight": 0.30,            # 價值投資權重
        "trend_weight": 0.30,            # 趨勢動能權重
        # 進出場閾值
        "buy_threshold": 0.4,            # 加權分數 > 此值才買入
        "sell_threshold": -0.3,          # 加權分數 < 此值才賣出
        "min_agree": 2,                  # 至少 N 個子策略同意
        # 法人跟單參數
        "inst_consecutive_days": 3,      # 法人連續買超天數
        # 價值投資參數
        "pe_threshold": 20,              # PE 上限
        "dividend_yield_min": 2.0,       # 殖利率下限
        # 趨勢動能參數
        "trend_period": 60,              # 趨勢判斷均線
        "fast_period": 10,               # 快線
        "slow_period": 30,               # 慢線
        # 持有控制
        "min_holding_days": 20,          # 最低持有天數
    }

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        n = len(df)

        # === 子策略 1：法人跟單分數 ===
        inst_score = self._calc_institutional_score(df)

        # === 子策略 2：價值投資分數 ===
        value_score = self._calc_value_score(df)

        # === 子策略 3：趨勢動能分數 ===
        trend_score = self._calc_trend_score(df)

        # === 加權組合 ===
        w_inst = self.params["institutional_weight"]
        w_val = self.params["value_weight"]
        w_trend = self.params["trend_weight"]

        total_score = (
            inst_score * w_inst +
            value_score * w_val +
            trend_score * w_trend
        )

        # 共識機制：計算同意的子策略數
        agree_buy = (
            (inst_score > 0).astype(int) +
            (value_score > 0).astype(int) +
            (trend_score > 0).astype(int)
        )
        agree_sell = (
            (inst_score < 0).astype(int) +
            (value_score < 0).astype(int) +
            (trend_score < 0).astype(int)
        )

        min_agree = self.params["min_agree"]
        buy_thresh = self.params["buy_threshold"]
        sell_thresh = self.params["sell_threshold"]
        min_hold = self.params["min_holding_days"]

        # 原始買賣條件
        raw_buy = (total_score > buy_thresh) & (agree_buy >= min_agree)
        raw_sell = (total_score < sell_thresh) & (agree_sell >= min_agree)

        # 使用狀態機實作最低持有期間
        signals = np.zeros(n, dtype=int)
        position = 0
        holding_count = 0

        for i in range(n):
            if position == 0:
                if raw_buy.iloc[i]:
                    signals[i] = 1
                    position = 1
                    holding_count = 0
            else:
                holding_count += 1
                if holding_count >= min_hold and raw_sell.iloc[i]:
                    signals[i] = -1
                    position = 0
                    holding_count = 0

        df["signal"] = signals

        # 保留子策略分數供分析
        df["inst_score"] = inst_score
        df["value_score"] = value_score
        df["trend_score"] = trend_score
        df["total_score"] = total_score

        return df

    def _calc_institutional_score(self, df: pd.DataFrame) -> pd.Series:
        """法人跟單分數 [-1, +1]"""
        score = pd.Series(0.0, index=df.index)

        buy_col = None
        for col in df.columns:
            if any(k in col.lower() for k in ["buy", "買", "foreign", "institutional"]):
                buy_col = col
                break

        if buy_col is None:
            return score

        n = self.params["inst_consecutive_days"]
        vals = pd.to_numeric(df[buy_col], errors="coerce").fillna(0)

        buying = (vals > 0).astype(int)
        selling = (vals < 0).astype(int)

        # 計算連續買超/賣超天數
        consecutive_buy = buying.copy()
        consecutive_sell = selling.copy()
        for i in range(1, n):
            consecutive_buy = consecutive_buy + buying.shift(i).fillna(0).astype(int)
            consecutive_sell = consecutive_sell + selling.shift(i).fillna(0).astype(int)

        # 連續 N 天買超 -> +1，連續 N 天賣超 -> -1
        score = score.where(~(consecutive_buy >= n), 1.0)
        score = score.where(~(consecutive_sell >= n), -1.0)

        # 中間狀態：根據最近的淨買賣方向給 0.5
        recent_buying = (vals > 0)
        recent_selling = (vals < 0)
        score = score.where(~((score == 0) & recent_buying), 0.3)
        score = score.where(~((score == 0) & recent_selling), -0.3)

        return score

    def _calc_value_score(self, df: pd.DataFrame) -> pd.Series:
        """價值投資分數 [-1, +1]"""
        score = pd.Series(0.0, index=df.index)
        conditions_met = pd.Series(0, index=df.index)
        total_conditions = 0

        # PE 條件
        pe_col = None
        for c in df.columns:
            if "PER" in c or c.lower() in ("pe", "per", "p/e"):
                pe_col = c
                break
        if pe_col is not None:
            pe = pd.to_numeric(df[pe_col], errors="coerce")
            valid_pe = pe.notna() & (pe > 0)
            conditions_met = conditions_met + (
                valid_pe & (pe < self.params["pe_threshold"])
            ).astype(int)
            # PE 太高扣分
            conditions_met = conditions_met - (
                valid_pe & (pe > 30)
            ).astype(int)
            total_conditions += 1

        # 殖利率條件
        dy_col = None
        for c in df.columns:
            if "dividend" in c.lower() or "yield" in c.lower() or "殖利率" in c:
                dy_col = c
                break
        if dy_col is not None:
            dy = pd.to_numeric(df[dy_col], errors="coerce")
            conditions_met = conditions_met + (
                dy > self.params["dividend_yield_min"]
            ).astype(int)
            total_conditions += 1

        # 營收成長條件
        rev_col = None
        for c in df.columns:
            if "yoy" in c.lower() or "growth" in c.lower() or "成長" in c:
                rev_col = c
                break
        if rev_col is not None:
            rev = pd.to_numeric(df[rev_col], errors="coerce")
            conditions_met = conditions_met + (rev > 0).astype(int)
            conditions_met = conditions_met - (rev < -10).astype(int)
            total_conditions += 1

        if total_conditions > 0:
            score = conditions_met / total_conditions
            score = score.clip(-1.0, 1.0)

        return score

    def _calc_trend_score(self, df: pd.DataFrame) -> pd.Series:
        """趨勢動能分數 [-1, +1]"""
        score = pd.Series(0.0, index=df.index)
        components = 0

        fast = self.params["fast_period"]
        slow = self.params["slow_period"]
        trend_p = self.params["trend_period"]

        # MA 趨勢方向
        fast_ma = _sma(df["close"], fast)
        slow_ma = _sma(df["close"], slow)
        trend_ma = _sma(df["close"], trend_p)

        # 快線在慢線上方 +1
        ma_cross = pd.Series(0.0, index=df.index)
        ma_cross = ma_cross.where(~(fast_ma > slow_ma), 1.0)
        ma_cross = ma_cross.where(~(fast_ma < slow_ma), -1.0)
        score = score + ma_cross
        components += 1

        # 價格在趨勢線上方 +1
        trend_dir = pd.Series(0.0, index=df.index)
        trend_dir = trend_dir.where(~(df["close"] > trend_ma), 1.0)
        trend_dir = trend_dir.where(~(df["close"] < trend_ma), -1.0)
        score = score + trend_dir
        components += 1

        # MACD 動能
        ema12 = _ema(df["close"], 12)
        ema26 = _ema(df["close"], 26)
        macd_line = ema12 - ema26
        signal_line = _ema(macd_line, 9)
        macd_hist = macd_line - signal_line

        macd_score = pd.Series(0.0, index=df.index)
        macd_score = macd_score.where(~(macd_hist > 0), 1.0)
        macd_score = macd_score.where(~(macd_hist < 0), -1.0)
        score = score + macd_score
        components += 1

        # 正規化到 [-1, 1]
        if components > 0:
            score = score / components

        return score
