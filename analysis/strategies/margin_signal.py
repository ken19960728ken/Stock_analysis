"""融資融券訊號策略 — 融資餘額減少 + 股價上漲 + MA 趨勢確認 + 券資比軋空偵測"""

import pandas as pd

from analysis.strategies.base import Strategy


class MarginSignalStrategy(Strategy):
    name = "融資融券訊號"
    description = "融資餘額減少 + 股價上漲 + MA 趨勢確認 = 籌碼沉澱（可選券資比軋空偵測）"
    params = {
        "margin_change_pct": -10.0,
        "lookback_days": 10,
        "require_price_ma_up": True,
        "use_short_ratio": False,
        "short_ratio_threshold": 30.0,
        "short_ratio_lookback": 5,
    }

    def _find_short_col(self, df: pd.DataFrame) -> str | None:
        """找融券餘額欄位"""
        candidates = [
            "ShortSaleTodayBalance", "short_sale_balance",
            "ShortSaleBalance", "short_sale_today_balance",
        ]
        for c in candidates:
            if c in df.columns:
                return c
        # fallback：含 short 且含 balance 的欄位
        for c in df.columns:
            cl = c.lower()
            if "short" in cl and "balance" in cl:
                return c
        return None

    def _find_margin_purchase_col(self, df: pd.DataFrame) -> str | None:
        """找融資餘額欄位（給券資比使用）"""
        candidates = [
            "MarginPurchaseTodayBalance", "margin_purchase_balance",
            "MarginPurchaseBalance", "margin_purchase_today_balance",
        ]
        for c in candidates:
            if c in df.columns:
                return c
        return None

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["signal"] = 0

        # 偵測融資餘額欄位
        margin_col = None
        # 優先精確匹配
        preferred = ["MarginPurchaseTodayBalance", "margin_purchase_balance",
                     "MarginPurchaseBalance", "margin_purchase_today_balance"]
        for c in preferred:
            if c in df.columns:
                margin_col = c
                break
        # fallback：含 margin + balance 但排除 short
        if margin_col is None:
            for c in df.columns:
                cl = c.lower()
                if "margin" in cl and "balance" in cl and "short" not in cl:
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

        # MA20 趨勢確認：要求 MA20 向上
        if self.params.get("require_price_ma_up", False) and "close" in df.columns:
            ma20 = df["close"].rolling(20, min_periods=5).mean()
            ma20_up = ma20 > ma20.shift(5)
            buy_cond = buy_cond & ma20_up

        buy_cond = buy_cond.eq(True)
        sell_cond = sell_cond.eq(True)
        prev_buy = buy_cond.shift(1, fill_value=False)
        prev_sell = sell_cond.shift(1, fill_value=False)

        df.loc[buy_cond & ~prev_buy, "signal"] = 1
        df.loc[sell_cond & ~prev_sell, "signal"] = -1

        # 券資比軋空偵測（預設關閉，不覆蓋既有訊號）
        if self.params.get("use_short_ratio", False):
            short_col = self._find_short_col(df)
            margin_p_col = self._find_margin_purchase_col(df)

            if short_col is not None and margin_p_col is not None:
                short_bal = pd.to_numeric(df[short_col], errors="coerce")
                margin_bal = pd.to_numeric(df[margin_p_col], errors="coerce")

                # 券資比 = 融券 / 融資 * 100
                short_ratio = short_bal / margin_bal.replace(0, float("nan")) * 100
                sr_lb = self.params.get("short_ratio_lookback", 5)
                short_ratio_smooth = short_ratio.rolling(sr_lb, min_periods=1).mean()

                sr_thresh = self.params.get("short_ratio_threshold", 30.0)
                sr_price_up = df["close"] > df["close"].shift(1)

                # 券資比超過門檻 + 股價上漲 → 軋空潛力（邊緣觸發）
                sr_cond = (short_ratio_smooth > sr_thresh) & sr_price_up
                sr_cond = sr_cond.eq(True)
                sr_prev = sr_cond.shift(1, fill_value=False)
                sr_edge = sr_cond & ~sr_prev

                # 不覆蓋現有訊號（signal==0 時才設為 1）
                df.loc[sr_edge & (df["signal"] == 0), "signal"] = 1

        return df
