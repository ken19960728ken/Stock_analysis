"""價值投資策略 — 低 P/E + 高殖利率 + 營收成長"""

import pandas as pd

from analysis.strategies.base import Strategy


class ValueInvestingStrategy(Strategy):
    name = "價值投資"
    description = "低本益比 + 高殖利率 + 營收正成長時買入，條件不滿足時賣出"
    params = {
        "pe_threshold": 15,
        "dividend_yield_threshold": 3.0,
        "revenue_growth_threshold": 0,
    }

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        data 需包含: PER, DividendYield, revenue_yoy 等欄位
        若缺少欄位則僅用可用的欄位判斷
        """
        df = data.copy()
        df["signal"] = 0

        score = pd.Series(0, index=df.index)
        conditions = 0

        # P/E 條件
        pe_col = None
        for c in df.columns:
            if "PER" in c or "pe" in c.lower():
                pe_col = c
                break
        if pe_col is not None:
            pe_vals = pd.to_numeric(df[pe_col], errors="coerce")
            valid_pe = pe_vals.notna() & (pe_vals > 0)
            score = score + (valid_pe & (pe_vals < self.params["pe_threshold"])).astype(int)
            conditions += 1

        # 殖利率條件
        dy_col = None
        for c in df.columns:
            if "dividend" in c.lower() or "yield" in c.lower() or "殖利率" in c:
                dy_col = c
                break
        if dy_col is not None:
            dy_vals = pd.to_numeric(df[dy_col], errors="coerce")
            score = score + (dy_vals > self.params["dividend_yield_threshold"]).astype(int)
            conditions += 1

        # 營收成長條件
        rev_col = None
        for c in df.columns:
            if "yoy" in c.lower() or "growth" in c.lower() or "成長" in c:
                rev_col = c
                break
        if rev_col is not None:
            rev_vals = pd.to_numeric(df[rev_col], errors="coerce")
            score = score + (rev_vals > self.params["revenue_growth_threshold"]).astype(int)
            conditions += 1

        if conditions == 0:
            return df

        threshold = max(conditions - 1, 1)  # 至少符合 N-1 個條件

        # 分數達標且前一期未達標 → 買入
        meets = score >= threshold
        df.loc[meets & (~meets.shift(1).fillna(False)), "signal"] = 1
        df.loc[(~meets) & meets.shift(1).fillna(False), "signal"] = -1

        return df
