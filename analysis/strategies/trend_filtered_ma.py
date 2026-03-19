"""
趨勢過濾型 MA 策略 — MA 交叉 + MA200 趨勢過濾 + 回檔反彈 + 最低持有期

改進原理：
1. MA200 趨勢過濾：只在價格位於 MA200 上方時做多（確認多頭趨勢），
   避免在下跌趨勢中逆勢操作，大幅減少假訊號。
2. 雙重進場條件：
   a) Golden Cross：MA 快線上穿慢線（經典交叉信號）
   b) 趨勢回檔反彈：在上升趨勢中（MA10 > MA40 > MA200），
      價格回檔至 MA10 附近後反彈，提供趨勢延續的進場機會。
3. 最低持有期間：原始 MA Cross 平均持有 3-5 天，過度交易導致手續費侵蝕利潤。
   設定最低持有期（預設 10 天），讓獲利趨勢有時間發展。
4. ATR 波動過濾：低波動盤整期的 MA 交叉幾乎都是雜訊。
   要求 ATR 百分比 > 閾值才觸發交易訊號。
5. 賣出改進：除了 death cross 賣出外，增加跌破 MA200 的保護性賣出。

理論基礎：
- Mebane Faber (2007) "A Quantitative Approach to Tactical Asset Allocation"
  證實 MA200 過濾可大幅降低下行風險
- 持有期間延長可降低交易成本影響，並捕捉中期趨勢
- 波動過濾避免低波動環境下的假突破
- 趨勢回檔進場（pullback entry）是動能策略的經典技巧
"""

import numpy as np
import pandas as pd

from analysis.strategies.base import Strategy
from analysis.utils.indicators import _ema, _sma


class TrendFilteredMAStrategy(Strategy):
    name = "趨勢過濾MA"
    description = "MA 交叉 + MA200 趨勢過濾 + 回檔反彈 + 最低持有期"
    params = {
        "fast_period": 10,          # 快線週期（原始 5 太短，改為 10）
        "slow_period": 40,          # 慢線週期（原始 20 太短，改為 40）
        "trend_period": 200,        # 趨勢判斷均線週期
        "min_holding_days": 15,     # 最低持有天數
        "atr_period": 14,           # ATR 計算週期
        "atr_threshold": 0.8,       # ATR 百分比閾值（%），低於此值不交易
        "use_trend_filter": True,   # 是否啟用趨勢過濾
        "use_atr_filter": True,     # 是否啟用波動過濾
        "trend_exit": True,         # 是否啟用跌破趨勢線賣出
        "use_pullback_entry": True, # 是否啟用回檔反彈進場
    }

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        fast = self.params["fast_period"]
        slow = self.params["slow_period"]
        trend_p = self.params["trend_period"]
        min_hold = self.params["min_holding_days"]
        atr_p = self.params["atr_period"]
        atr_thresh = self.params["atr_threshold"]
        use_trend = self.params["use_trend_filter"]
        use_atr = self.params["use_atr_filter"]
        trend_exit = self.params["trend_exit"]
        use_pullback = self.params["use_pullback_entry"]

        # 計算均線
        df["fast_ma"] = _sma(df["close"], fast)
        df["slow_ma"] = _sma(df["close"], slow)
        df["trend_ma"] = _sma(df["close"], trend_p)

        # 計算 ATR 百分比
        high_low = df["high"] - df["low"]
        high_prev_close = (df["high"] - df["close"].shift(1)).abs()
        low_prev_close = (df["low"] - df["close"].shift(1)).abs()
        tr = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1 / atr_p, min_periods=atr_p, adjust=False).mean()
        df["atr_pct"] = atr / df["close"] * 100  # ATR 佔股價的百分比

        # --- 進場條件 1: 基本 MA 交叉 ---
        golden_cross = (
            (df["fast_ma"] > df["slow_ma"]) &
            (df["fast_ma"].shift(1) <= df["slow_ma"].shift(1))
        )

        # --- 進場條件 2: 回檔反彈進場 ---
        # 條件：快線 > 慢線（趨勢向上），價格曾回檔至快線以下（2天內），現在反彈回快線上方
        pullback_entry = pd.Series(False, index=df.index)
        if use_pullback:
            uptrend_momentum = df["fast_ma"] > df["slow_ma"]
            # 過去 3 天內曾低於 fast_ma
            was_below_fast = pd.Series(False, index=df.index)
            for lag in range(1, 4):
                was_below_fast = was_below_fast | (
                    df["close"].shift(lag) < df["fast_ma"].shift(lag)
                )
            # 現在回到 fast_ma 上方
            now_above_fast = df["close"] > df["fast_ma"]
            prev_below_fast = df["close"].shift(1) <= df["fast_ma"].shift(1)
            pullback_entry = (
                uptrend_momentum &
                was_below_fast &
                now_above_fast &
                prev_below_fast
            )

        # 合併進場條件
        entry_signal = golden_cross | pullback_entry

        # 趨勢過濾：只在多頭趨勢中做多
        if use_trend:
            in_uptrend = df["close"] > df["trend_ma"]
            entry_signal = entry_signal & in_uptrend

        # ATR 波動過濾：排除低波動環境
        if use_atr:
            sufficient_vol = df["atr_pct"] > atr_thresh
            entry_signal = entry_signal & sufficient_vol

        # --- 出場條件: Death Cross ---
        death_cross = (
            (df["fast_ma"] < df["slow_ma"]) &
            (df["fast_ma"].shift(1) >= df["slow_ma"].shift(1))
        )

        # 生成原始訊號
        df["signal"] = 0

        # 使用狀態機實作最低持有期間
        position = 0  # 0=空手, 1=持有
        holding_count = 0

        signals = np.zeros(len(df), dtype=int)

        for i in range(len(df)):
            if position == 0:
                # 空手狀態：檢查買入條件
                if entry_signal.iloc[i]:
                    signals[i] = 1
                    position = 1
                    holding_count = 0
            else:
                # 持有狀態
                holding_count += 1

                # 保護性賣出：跌破趨勢線（不受最低持有期限制，獨立於 use_trend）
                if trend_exit:
                    if pd.notna(df["trend_ma"].iloc[i]):
                        if df["close"].iloc[i] < df["trend_ma"].iloc[i] * 0.98:
                            signals[i] = -1
                            position = 0
                            holding_count = 0
                            continue

                # 最低持有期間限制
                if holding_count < min_hold:
                    continue

                # 正常賣出：death cross
                if death_cross.iloc[i]:
                    signals[i] = -1
                    position = 0
                    holding_count = 0

        df["signal"] = signals
        return df
