"""自由現金流策略 — 營運現金流為正且 FCF Yield 達標時買入"""

import pandas as pd

from analysis.strategies.base import Strategy


class FreeCashFlowStrategy(Strategy):
    name = "自由現金流"
    description = "營運現金流為正且自由現金流殖利率達標時買入"
    params = {
        "fcf_yield_threshold": 3.0,
        "ocf_positive_required": True,
    }

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["signal"] = 0

        # 偵測營運現金流欄位
        ocf_col = None
        for c in df.columns:
            cl = c.lower()
            if any(k in cl for k in ["cashflowsfromoperating", "ocf", "operating_cash"]):
                ocf_col = c
                break

        if ocf_col is None:
            return df

        ocf = pd.to_numeric(df[ocf_col], errors="coerce")

        # 偵測 CapEx 欄位：FCF = OCF - CapEx（Jensen 1986）
        capex_col = None
        for c in df.columns:
            cl = c.lower()
            if any(k in cl for k in ["capitalexpenditure", "capex", "資本支出"]):
                capex_col = c
                break

        capex = pd.to_numeric(df[capex_col], errors="coerce").abs().fillna(0) if capex_col else 0
        fcf = ocf - capex

        # 偵測市值欄位（用於計算 FCF Yield）
        mv_col = None
        for c in df.columns:
            if "market_value" in c.lower() or c.lower() == "marketvalue":
                mv_col = c
                break

        if mv_col is not None:
            mv = pd.to_numeric(df[mv_col], errors="coerce")
            fcf_yield = fcf / mv.replace(0, float("nan")) * 100

            if self.params["ocf_positive_required"]:
                condition = (ocf > 0) & (fcf_yield >= self.params["fcf_yield_threshold"])
            else:
                condition = fcf_yield >= self.params["fcf_yield_threshold"]
        else:
            # 無市值資料：降級為只看 OCF 正負
            condition = ocf > 0

        meets = condition.eq(True)
        prev_meets = meets.shift(1, fill_value=False)
        df.loc[meets & ~prev_meets, "signal"] = 1
        df.loc[~meets & prev_meets, "signal"] = -1

        return df
