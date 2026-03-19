"""法人跟單策略 — 連續 N 日買超 + 價格動能確認 + 法人拆分"""

import pandas as pd

from analysis.strategies.base import Strategy


class InstitutionalStrategy(Strategy):
    name = "法人跟單"
    description = "法人連續 N 日買超 + 價格在 MA20 上方 → 買入（支援拆分三法人）"
    params = {
        "consecutive_days": 5,
        "focus": "all",
        "require_all_three": False,
    }

    def _get_net_buy_series(self, df: pd.DataFrame, focus: str) -> pd.Series | None:
        """依 focus 計算對應法人淨買超"""
        # 嘗試找拆分欄位
        col_map = {
            "foreign": ("foreign_investors_buy", "foreign_investors_sell"),
            "trust": ("investment_trust_buy", "investment_trust_sell"),
            "dealer": ("dealer_buy", "dealer_sell"),
        }

        if focus in col_map:
            buy_col, sell_col = col_map[focus]
            if buy_col in df.columns and sell_col in df.columns:
                return pd.to_numeric(df[buy_col], errors="coerce").fillna(0) - \
                       pd.to_numeric(df[sell_col], errors="coerce").fillna(0)

        # focus == "all" 或拆分欄位不存在 → 找合計欄位
        if "institutional_net_buy" in df.columns:
            return pd.to_numeric(df["institutional_net_buy"], errors="coerce")

        # fallback：優先匹配含 net 的欄位（淨買超），避免誤取單邊買入
        for col in df.columns:
            cl = col.lower()
            if "net" in cl and any(k in cl for k in ["buy", "買", "foreign", "institutional"]):
                return pd.to_numeric(df[col], errors="coerce")
        # 最後 fallback：法人買賣超等合計欄位
        for col in df.columns:
            cl = col.lower()
            if cl in ("法人買賣超", "institutional_buy_sell"):
                return pd.to_numeric(df[col], errors="coerce")

        return None

    def _check_all_three_buy(self, df: pd.DataFrame) -> pd.Series:
        """三法人各自當日淨買超均 > 0"""
        pairs = [
            ("foreign_investors_buy", "foreign_investors_sell"),
            ("investment_trust_buy", "investment_trust_sell"),
            ("dealer_buy", "dealer_sell"),
        ]
        result = pd.Series(True, index=df.index)
        found = False
        for buy_col, sell_col in pairs:
            if buy_col in df.columns and sell_col in df.columns:
                found = True
                net = pd.to_numeric(df[buy_col], errors="coerce").fillna(0) - \
                      pd.to_numeric(df[sell_col], errors="coerce").fillna(0)
                result = result & (net > 0)
        # 若拆分欄位完全不存在，退回 False（不啟用此過濾）
        if not found:
            return pd.Series(False, index=df.index)
        return result

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["signal"] = 0

        focus = self.params.get("focus", "all")
        net_buy = self._get_net_buy_series(df, focus)

        if net_buy is None:
            return df

        n = self.params["consecutive_days"]
        buying = (net_buy > 0).astype(int)
        selling = (net_buy < 0).astype(int)

        consecutive_buy = buying.copy()
        consecutive_sell = selling.copy()
        for i in range(1, n):
            consecutive_buy = consecutive_buy + buying.shift(i).fillna(0).astype(int)
            consecutive_sell = consecutive_sell + selling.shift(i).fillna(0).astype(int)

        buy_cond = (consecutive_buy >= n) & (consecutive_buy.shift(1) < n)
        sell_cond = (consecutive_sell >= n) & (consecutive_sell.shift(1) < n)

        # 三法人共買過濾
        if self.params.get("require_all_three", False):
            all_three = self._check_all_three_buy(df)
            buy_cond = buy_cond & all_three

        # 價格動能確認：價格需在 MA20 上方（不逆勢跟單）
        if "close" in df.columns:
            ma20 = df["close"].rolling(20, min_periods=1).mean()
            buy_cond = buy_cond & (df["close"] > ma20)

        df.loc[buy_cond, "signal"] = 1
        df.loc[sell_cond, "signal"] = -1

        return df
