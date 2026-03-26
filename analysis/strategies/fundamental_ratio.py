"""財報三率策略 — 毛利率、營業利益率、淨利率篩選"""

import pandas as pd

from analysis.strategies.base import Strategy


class FundamentalRatioStrategy(Strategy):
    name = "財報三率"
    description = "毛利率、營業利益率、淨利率三率篩選，N 個達標即買入"
    params = {
        "gross_margin_threshold": 25.0,
        "operating_margin_threshold": 10.0,
        "net_margin_threshold": 8.0,
        "min_conditions": 2,
    }

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["signal"] = 0

        score = pd.Series(0, index=df.index)
        available = 0

        # --- 毛利率 ---
        gp_col = None
        rev_col = None
        for c in df.columns:
            cl = c.lower()
            if gp_col is None and ("grossprofit" in cl or "gross_profit" in cl):
                gp_col = c
            if rev_col is None and (
                cl == "revenue"
                or ("revenue" in cl and "yoy" not in cl and "month" not in cl and "year" not in cl)
            ):
                rev_col = c

        if gp_col and rev_col:
            gp = pd.to_numeric(df[gp_col], errors="coerce")
            rev = pd.to_numeric(df[rev_col], errors="coerce")
            gross_margin = gp / rev.replace(0, float("nan")) * 100
            score = score + (gross_margin >= self.params["gross_margin_threshold"]).astype(int)
            available += 1

        # --- 營業利益率 ---
        oi_col = None
        for c in df.columns:
            if "operatingincome" in c.lower() or "operating_income" in c.lower():
                oi_col = c
                break

        if oi_col and rev_col:
            oi = pd.to_numeric(df[oi_col], errors="coerce")
            rev = pd.to_numeric(df[rev_col], errors="coerce")
            op_margin = oi / rev.replace(0, float("nan")) * 100
            score = score + (op_margin >= self.params["operating_margin_threshold"]).astype(int)
            available += 1

        # --- 淨利率 ---
        ni_col = None
        for c in df.columns:
            if "incomeaftertaxes" in c.lower() or "netincome" in c.lower() or "net_income" in c.lower():
                ni_col = c
                break

        if ni_col and rev_col:
            ni = pd.to_numeric(df[ni_col], errors="coerce")
            rev = pd.to_numeric(df[rev_col], errors="coerce")
            net_margin = ni / rev.replace(0, float("nan")) * 100
            score = score + (net_margin >= self.params["net_margin_threshold"]).astype(int)
            available += 1

        if available == 0:
            return df

        # Graceful degradation: 若可用指標不足，降低門檻
        min_cond = min(self.params["min_conditions"], available)

        meets = (score >= min_cond).astype(bool)
        prev_meets = meets.shift(1, fill_value=False).astype(bool)
        df.loc[meets & ~prev_meets, "signal"] = 1
        df.loc[~meets & prev_meets, "signal"] = -1

        return df
