"""法人跟單策略 — 連續 N 日買超 + 價格動能確認進場"""

import pandas as pd

from analysis.strategies.base import Strategy


class InstitutionalStrategy(Strategy):
    name = "法人跟單"
    description = "法人連續 N 日買超 + 價格在 MA20 上方 → 買入"
    params = {"consecutive_days": 5}

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        data 需包含 'institutional_buy' 欄位（法人淨買賣超，正=買超，負=賣超）
        若無此欄位，嘗試從其他可能的欄位名稱取得
        """
        df = data.copy()
        df["signal"] = 0

        buy_col = None
        for col in df.columns:
            if any(k in col.lower() for k in ["buy", "買", "foreign", "institutional"]):
                buy_col = col
                break

        if buy_col is None:
            return df

        n = self.params["consecutive_days"]
        buying = (df[buy_col] > 0).astype(int)
        selling = (df[buy_col] < 0).astype(int)

        consecutive_buy = buying.copy()
        consecutive_sell = selling.copy()
        for i in range(1, n):
            consecutive_buy = consecutive_buy + buying.shift(i).fillna(0).astype(int)
            consecutive_sell = consecutive_sell + selling.shift(i).fillna(0).astype(int)

        buy_cond = (consecutive_buy >= n) & (consecutive_buy.shift(1) < n)
        sell_cond = (consecutive_sell >= n) & (consecutive_sell.shift(1) < n)

        # 價格動能確認：價格需在 MA20 上方（不逆勢跟單）
        if "close" in df.columns:
            ma20 = df["close"].rolling(20, min_periods=1).mean()
            buy_cond = buy_cond & (df["close"] > ma20)

        df.loc[buy_cond, "signal"] = 1
        df.loc[sell_cond, "signal"] = -1

        return df
