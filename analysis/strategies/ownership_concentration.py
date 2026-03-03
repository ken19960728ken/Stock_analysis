"""股權集中度策略 — 大股東持股增加 + 股東人數減少 → 買入"""

import pandas as pd

from analysis.strategies.base import Strategy


class OwnershipConcentrationStrategy(Strategy):
    name = "股權集中度"
    description = "大股東持股增加 + 股東人數減少 → 籌碼集中 → 買入"
    params = {
        "holder_increase_threshold": 0.5,
        "shareholder_decrease_threshold": -2.0,
        "lookback_periods": 4,
    }

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["signal"] = 0

        # 偵測持股比例欄位
        hp_col = None
        for c in df.columns:
            if "holding_percentage" in c.lower() or "持股比例" in c:
                hp_col = c
                break

        # 偵測股東人數欄位
        sc_col = None
        for c in df.columns:
            if "shareholder_count" in c.lower() or "股東人數" in c:
                sc_col = c
                break

        if hp_col is None and sc_col is None:
            return df

        lb = self.params["lookback_periods"]
        # 每 lookback 單位代表約 1 週（5 交易日），因為籌碼資料是 forward-fill 到 daily
        effective_lb = lb * 5
        conditions = 0
        buy_mask = pd.Series(True, index=df.index)

        if hp_col is not None:
            hp = pd.to_numeric(df[hp_col], errors="coerce")
            hp_change = hp - hp.shift(effective_lb)
            holder_cond = hp_change >= self.params["holder_increase_threshold"]
            buy_mask = buy_mask & holder_cond.eq(True)
            conditions += 1

        if sc_col is not None:
            sc = pd.to_numeric(df[sc_col], errors="coerce")
            sc_prev = sc.shift(effective_lb)
            sc_pct_change = (sc - sc_prev) / sc_prev.replace(0, float("nan")) * 100
            shareholder_cond = sc_pct_change <= self.params["shareholder_decrease_threshold"]
            buy_mask = buy_mask & shareholder_cond.eq(True)
            conditions += 1

        if conditions == 0:
            return df

        meets = buy_mask.eq(True)
        prev_meets = meets.shift(1, fill_value=False)
        df.loc[meets & ~prev_meets, "signal"] = 1
        df.loc[~meets & prev_meets, "signal"] = -1

        return df
