"""融資融券訊號策略 — 融資餘額減少 + 股價上漲 = 籌碼沉澱"""

import pandas as pd

from analysis.strategies.base import Strategy


class MarginSignalStrategy(Strategy):
    name = "融資融券訊號"
    description = "融資餘額減少 + 股價上漲 = 籌碼沉澱，買入訊號"
    params = {
        "margin_change_pct": -5.0,
        "lookback_days": 5,
    }

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["signal"] = 0

        # 偵測融資餘額欄位
        margin_col = None
        for c in df.columns:
            if "margin_purchase_balance" in c.lower() or "margin" in c.lower() and "short" not in c.lower():
                margin_col = c
                break

        if margin_col is None:
            return df

        lb = self.params["lookback_days"]
        threshold = self.params["margin_change_pct"]

        margin = pd.to_numeric(df[margin_col], errors="coerce")
        margin_prev = margin.shift(lb)
        margin_pct_change = (margin - margin_prev) / margin_prev.replace(0, float("nan")) * 100

        price_up = df["close"] > df["close"].shift(lb)
        price_down = df["close"] < df["close"].shift(lb)

        # 買入：融資餘額下降（<= threshold）且股價上漲
        buy_cond = (margin_pct_change <= threshold) & price_up
        # 賣出：融資餘額大增（> |threshold|）且股價下跌
        sell_cond = (margin_pct_change >= abs(threshold)) & price_down

        buy_cond = buy_cond.eq(True)
        sell_cond = sell_cond.eq(True)
        prev_buy = buy_cond.shift(1, fill_value=False)
        prev_sell = sell_cond.shift(1, fill_value=False)

        df.loc[buy_cond & ~prev_buy, "signal"] = 1
        df.loc[sell_cond & ~prev_sell, "signal"] = -1

        return df
