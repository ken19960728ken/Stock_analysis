"""法人跟單策略 — 連續 N 日買超進場"""

import pandas as pd

from analysis.strategies.base import Strategy


class InstitutionalStrategy(Strategy):
    name = "法人跟單"
    description = "法人連續 N 日買超買入，連續 N 日賣超賣出"
    params = {"consecutive_days": 3}

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

        df.loc[
            (consecutive_buy >= n) & (consecutive_buy.shift(1) < n),
            "signal"
        ] = 1
        df.loc[
            (consecutive_sell >= n) & (consecutive_sell.shift(1) < n),
            "signal"
        ] = -1

        return df
