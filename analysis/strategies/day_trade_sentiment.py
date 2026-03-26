"""
當沖情緒反轉策略 — 當沖比例 Z-Score 作為散戶情緒反向指標

學理來源：
- Barber, B.M. & Odean, T. (2000). "Trading Is Hazardous to Your Wealth."
  Journal of Finance, 55(2), 773-800.
- Barber, B.M., Lee, Y.T., Liu, Y.J., & Odean, T. (2009). "Just How Much Do
  Individual Investors Lose by Trading?" Review of Financial Studies, 22(2), 609-632.
- Kumar, A. (2009). "Who Gambles in the Stock Market?" Journal of Finance, 64(4),
  1889-1933.

Claude 設計（原創部分）：
- 當沖比例 Z-Score 標準化（用 60 天滾動窗口）
- 當沖損益方向作為輔助信號（SellAmount - BuyAmount）
- Z-Score 閾值逆向交易（> 2.0 賣出，< -1.5 買入）
"""

import pandas as pd

from analysis.strategies.base import Strategy


class DayTradeSentimentStrategy(Strategy):
    name = "當沖情緒反轉"
    description = "當沖比例 Z-Score 作為散戶情緒反向指標"
    params = {
        "zscore_window": 60,         # Z-Score 滾動窗口（交易日）
        "overbought_z": 2.0,        # 過熱閾值（賣出）
        "oversold_z": -1.5,         # 過冷閾值（買入）
        "min_day_trade_ratio": 0.01, # 最低當沖比例（過濾冷門股）
        "max_day_trade_ratio": 0.50, # 最高當沖比例（過濾投機股）
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

        # === 偵測當沖比例欄位 ===
        ratio_col = self._find_col(df, ["day_trade_ratio", "daytraderatio"])
        dt_vol_col = self._find_col(df, ["day_trade_volume", "daytradevolume"])
        vol_col = self._find_col(df, ["volume"])

        # 計算當沖比例
        if ratio_col is not None:
            day_trade_ratio = pd.to_numeric(df[ratio_col], errors="coerce")
        elif dt_vol_col is not None and vol_col is not None:
            dt_vol = pd.to_numeric(df[dt_vol_col], errors="coerce")
            vol = pd.to_numeric(df[vol_col], errors="coerce").replace(0, float("nan"))
            day_trade_ratio = dt_vol / vol
        else:
            # 無當沖資料，靜默返回
            return df

        # === 過濾條件：當沖比例在合理範圍 ===
        min_ratio = self.params["min_day_trade_ratio"]
        max_ratio = self.params["max_day_trade_ratio"]
        valid_ratio = (day_trade_ratio >= min_ratio) & (day_trade_ratio <= max_ratio)

        # === 計算 Z-Score ===
        window = self.params["zscore_window"]
        rolling_mean = day_trade_ratio.rolling(window=window, min_periods=max(1, window // 2)).mean()
        rolling_std = day_trade_ratio.rolling(window=window, min_periods=max(1, window // 2)).std()
        zscore = (day_trade_ratio - rolling_mean) / rolling_std.replace(0, float("nan"))

        # === 訊號生成 ===
        overbought_z = self.params["overbought_z"]
        oversold_z = self.params["oversold_z"]

        # 買入：Z-Score < oversold_z（散戶離場，情緒過冷）+ 當沖比例合理
        buy_condition = (zscore < oversold_z) & valid_ratio
        # 賣出：Z-Score > overbought_z（散戶瘋狂，情緒過熱）+ 當沖比例合理
        sell_condition = (zscore > overbought_z) & valid_ratio

        # 邊緣偵測
        meets_buy = buy_condition.fillna(False)
        meets_sell = sell_condition.fillna(False)
        prev_buy = meets_buy.shift(1, fill_value=False)
        prev_sell = meets_sell.shift(1, fill_value=False)

        df.loc[meets_buy & ~prev_buy, "signal"] = 1
        df.loc[meets_sell & ~prev_sell, "signal"] = -1

        return df
