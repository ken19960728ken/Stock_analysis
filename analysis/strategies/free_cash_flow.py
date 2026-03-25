"""
自由現金流策略 — Level 2 + Level 3

Level 1: OCF > 0 + FCF Yield 達標（Jensen 1986, Lakonishok et al. 1994）
Level 2: OCF 呈上升趨勢（近期 > N 天前）
Level 3: 盈餘品質 = OCF / NI > 門檻（Sloan 1996, Piotroski 2000）

學理來源：
- Jensen, M.C. (1986). "Agency Costs of Free Cash Flow." AER, 76(2), 323-329.
- Lakonishok, J., Shleifer, A., & Vishny, R.W. (1994). "Contrarian Investment." JoF, 49(5), 1541-1578.
- Piotroski, J.D. (2000). "Value Investing." JAR, 38, 1-41.
- Sloan, R.G. (1996). "Do Stock Prices Fully Reflect Information in Accruals?" AR, 71(3), 289-315.
"""

import pandas as pd

from analysis.strategies.base import Strategy


class FreeCashFlowStrategy(Strategy):
    name = "自由現金流"
    description = "OCF 趨勢向上、FCF Yield 達標、盈餘品質過濾"
    params = {
        "fcf_yield_threshold": 3.0,   # FCF Yield 門檻 (%)
        "ocf_positive_required": True, # OCF 必須為正
        "earnings_quality_min": 0.5,   # 盈餘品質下限 (OCF/NI)
        "trend_quarters": 4,           # 趨勢比較季數
        "enable_quality_filter": True, # 啟用盈餘品質過濾 (Level 3)
    }

    def _find_col(self, df: pd.DataFrame, keywords: list[str]) -> str | None:
        """動態搜尋欄位名稱（case-insensitive）"""
        for c in df.columns:
            cl = c.lower()
            if any(k in cl for k in keywords):
                return c
        return None

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["signal"] = 0

        # === 偵測營運現金流欄位 ===
        ocf_col = self._find_col(df, ["cashflowsfromoperating", "ocf", "operating_cash"])
        if ocf_col is None:
            return df

        ocf = pd.to_numeric(df[ocf_col], errors="coerce")

        # === 偵測 CapEx 欄位：FCF = OCF - CapEx（Jensen 1986） ===
        capex_col = self._find_col(
            df, ["propertyandplantandequipment", "capitalexpenditure", "capex", "資本支出"]
        )
        capex = (
            pd.to_numeric(df[capex_col], errors="coerce").abs().fillna(0)
            if capex_col
            else 0
        )
        fcf = ocf - capex

        # === 偵測市值欄位（用於計算 FCF Yield） ===
        mv_col = self._find_col(df, ["market_value", "marketvalue"])

        # === 偵測淨利欄位（Level 3 盈餘品質） ===
        ni_col = self._find_col(
            df, ["incomeaftertaxes", "netincome", "net_income", "稅後淨利"]
        )

        # === 條件 1: OCF > 0（Piotroski 2000） ===
        ocf_positive = ocf > 0

        # === 條件 2+3: FCF Yield（Lakonishok 1994） ===
        if mv_col is not None:
            mv = pd.to_numeric(df[mv_col], errors="coerce")
            fcf_yield = fcf / mv.replace(0, float("nan")) * 100
            yield_ok = fcf_yield >= self.params["fcf_yield_threshold"]
            # 賣出條件：FCF Yield < 1%（過高估值）
            yield_sell = fcf_yield < 1.0
        else:
            # 無市值資料：降級為只看 OCF 正負
            yield_ok = ocf_positive
            fcf_yield = pd.Series(float("nan"), index=df.index)
            yield_sell = pd.Series(False, index=df.index)

        # === Level 2: OCF 趨勢向上 ===
        trend_q = self.params["trend_quarters"]
        # 季度資料用 ffill，比較 shift(trend_q) 前的值
        ocf_filled = ocf.ffill()
        ocf_prev = ocf_filled.shift(trend_q)
        # 有前期資料時才比較，無前期資料時此條件預設通過
        ocf_trend_up = (ocf_filled > ocf_prev) | ocf_prev.isna()

        # === Level 3: 盈餘品質（Sloan 1996） ===
        if self.params["enable_quality_filter"] and ni_col is not None:
            ni = pd.to_numeric(df[ni_col], errors="coerce")
            # 避免除以零
            earnings_quality = ocf / ni.replace(0, float("nan"))
            quality_buy = (earnings_quality >= self.params["earnings_quality_min"]) | earnings_quality.isna()
            quality_sell = (earnings_quality < 0.3) & earnings_quality.notna()
        else:
            quality_buy = pd.Series(True, index=df.index)
            quality_sell = pd.Series(False, index=df.index)

        # === 買入條件：全部滿足 ===
        if self.params["ocf_positive_required"]:
            buy_condition = ocf_positive & yield_ok & ocf_trend_up & quality_buy
        else:
            buy_condition = yield_ok & ocf_trend_up & quality_buy

        # === 賣出條件：任一滿足 ===
        sell_condition = (~ocf_positive) | yield_sell | quality_sell

        # === 訊號生成（狀態切換邊緣偵測） ===
        meets = buy_condition & ~sell_condition
        prev_meets = meets.shift(1, fill_value=False)
        df.loc[meets & ~prev_meets, "signal"] = 1
        df.loc[~meets & prev_meets, "signal"] = -1

        return df
