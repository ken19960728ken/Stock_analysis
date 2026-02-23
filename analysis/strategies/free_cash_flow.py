"""自由現金流策略 — 營運現金流為正且 FCF Yield 達標時買入"""

import pandas as pd

from analysis.strategies.base import Strategy


class FreeCashFlowStrategy(Strategy):
    name = "自由現金流"
    description = "營運現金流為正且自由現金流殖利率達標時買入"
    params = {
        "fcf_yield_threshold": 5.0,
        "ocf_positive_required": True,
    }

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["signal"] = 0

        # 偵測營運現金流欄位
        ocf_col = None
        for c in df.columns:
            if "cashflowsfromoperating" in c.lower() or "ocf" == c.lower():
                ocf_col = c
                break

        if ocf_col is None:
            return df

        ocf = pd.to_numeric(df[ocf_col], errors="coerce")

        # 偵測市值欄位（用於計算 FCF Yield）
        mv_col = None
        for c in df.columns:
            if "market_value" in c.lower() or c.lower() == "marketvalue":
                mv_col = c
                break

        if mv_col is not None:
            mv = pd.to_numeric(df[mv_col], errors="coerce")
            fcf_yield = ocf / mv.replace(0, float("nan")) * 100

            if self.params["ocf_positive_required"]:
                condition = (ocf > 0) & (fcf_yield >= self.params["fcf_yield_threshold"])
            else:
                condition = fcf_yield >= self.params["fcf_yield_threshold"]
        else:
            # 無市值資料：降級為只看 OCF 正負
            condition = ocf > 0

        meets = condition.fillna(False).astype(bool)
        prev_meets = meets.shift(1).fillna(False).astype(bool)
        df.loc[meets & ~prev_meets, "signal"] = 1
        df.loc[~meets & prev_meets, "signal"] = -1

        return df
