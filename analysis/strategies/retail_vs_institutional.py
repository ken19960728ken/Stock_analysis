"""
散戶vs主力反向指標 -- 當沖情緒 x 外資動向四象限

學理來源:
- Barber, B.M. & Odean, T. (2000). "Trading Is Hazardous to Your Wealth."
  Journal of Finance, 55(2), 773-800.
- Barber, B.M., Lee, Y.T., Liu, Y.J., & Odean, T. (2009). "Just How Much
  Do Individual Investors Lose by Trading?" Review of Financial Studies,
  22(2), 609-632.
  -- 台灣散戶當沖交易者整體虧損

Claude 設計（原創部分）:
- 當沖比例 Z-Score x 外資淨買超方向 四象限模型
- 散戶冷 + 主力買 = 最佳買入象限
- 散戶熱 + 主力賣 = 最佳賣出象限
"""

import numpy as np
import pandas as pd

from analysis.strategies.base import Strategy


class RetailVsInstitutionalStrategy(Strategy):
    name = "散戶vs主力"
    description = "當沖情緒 x 外資動向四象限反向交易"
    params = {
        "zscore_window": 60,
        "overbought_z": 1.5,
        "oversold_z": -1.0,
        "foreign_consecutive": 3,
        "max_hold_days": 15,
    }

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["signal"] = 0

        # 偵測 day_trade_volume 欄位（由 enrich_data 從 day_trading 合併）
        dt_col = None
        for c in df.columns:
            if "day_trade_volume" in c.lower():
                dt_col = c
                break
        if dt_col is None or "volume" not in df.columns:
            return df

        # 偵測 foreign_net 欄位（由 enrich_data 從 chip_broker 合併）
        net_col = None
        for c in df.columns:
            if c.lower() in ("foreign_net", "foreign_net_buy"):
                net_col = c
                break
        if net_col is None:
            return df

        # 計算當沖比例
        day_trade_vol = pd.to_numeric(df[dt_col], errors="coerce").fillna(0)
        total_vol = pd.to_numeric(df["volume"], errors="coerce").replace(
            0, float("nan")
        )
        ratio = day_trade_vol / total_vol

        # Z-Score
        window = self.params["zscore_window"]
        ratio_mean = ratio.rolling(window, min_periods=20).mean()
        ratio_std = ratio.rolling(window, min_periods=20).std()
        z_score = (ratio - ratio_mean) / ratio_std.replace(0, float("nan"))

        # 外資連續買/賣超
        foreign_net = pd.to_numeric(df[net_col], errors="coerce").fillna(0)
        consec = self.params["foreign_consecutive"]
        foreign_buy_streak = (
            (foreign_net > 0).astype(int).rolling(consec, min_periods=consec).sum()
            >= consec
        )
        foreign_sell_streak = (
            (foreign_net < 0).astype(int).rolling(consec, min_periods=consec).sum()
            >= consec
        )

        oversold_z = self.params["oversold_z"]
        overbought_z = self.params["overbought_z"]
        max_hold = self.params["max_hold_days"]

        # 四象限
        # 散戶冷 + 主力買 -> 買入
        buy = (z_score < oversold_z) & foreign_buy_streak
        # 散戶熱 + 主力賣 -> 賣出
        sell = (z_score > overbought_z) & foreign_sell_streak

        signal = pd.Series(0, index=df.index)
        signal[buy] = 1
        signal[sell] = -1

        if max_hold > 0:
            df["signal"] = self._apply_max_hold(signal, max_hold)
        else:
            df["signal"] = signal

        return df

    @staticmethod
    def _apply_max_hold(signal: pd.Series, max_hold: int) -> pd.Series:
        """追蹤持倉狀態，超過 max_hold 天強制賣出"""
        vals = signal.values.copy()
        out = np.zeros(len(vals), dtype=int)
        in_position = False
        entry_idx = 0
        for i in range(len(vals)):
            s = vals[i]
            if not in_position:
                if s == 1:
                    in_position = True
                    entry_idx = i
                    out[i] = 1
            else:
                days_held = i - entry_idx
                if s == -1 or days_held >= max_hold:
                    out[i] = -1
                    in_position = False
        return pd.Series(out, index=signal.index)
