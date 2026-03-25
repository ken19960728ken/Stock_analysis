"""
外資連續買超策略 -- 追蹤外資券商連續買超行為

學理來源:
- Sias, R.W. (2004). "Institutional Herding." Review of Financial Studies,
  17(1), 165-206.
  -- 機構投資者有羊群效應，連續同方向交易預測未來報酬
- Nofsinger, J.R. & Sias, R.W. (1999). "Herding and Feedback Trading by
  Institutional and Individual Investors." Journal of Finance, 54(6),
  2263-2295.
  -- 機構投資者的正反饋交易具有預測能力

Claude 設計（原創部分）:
- 多券商共買確認機制（min_brokers 門檻）
- 累積淨買超佔日均量比例作為力道指標
- 最大持有天數強制出場
"""

import numpy as np
import pandas as pd

from analysis.strategies.base import Strategy


class ForeignBrokerTrackingStrategy(Strategy):
    name = "外資連續買超"
    description = "追蹤外資券商連續買超，多券商共買確認"
    params = {
        "consecutive_days": 3,
        "min_brokers": 3,
        "net_volume_pct": 0.05,
        "max_hold_days": 20,
    }

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["signal"] = 0

        # 偵測 foreign_net 欄位（由 enrich_data 從 chip_broker 合併）
        net_col = None
        for c in df.columns:
            if c.lower() in ("foreign_net", "foreign_net_buy"):
                net_col = c
                break
        if net_col is None:
            return df

        # 偵測 foreign_broker_count 欄位
        count_col = None
        for c in df.columns:
            if "foreign_broker_count" in c.lower():
                count_col = c
                break

        net = pd.to_numeric(df[net_col], errors="coerce").fillna(0)
        broker_count = (
            pd.to_numeric(df[count_col], errors="coerce").fillna(0)
            if count_col
            else pd.Series(8, index=df.index)
        )

        consecutive = self.params["consecutive_days"]
        min_brokers = self.params["min_brokers"]
        net_vol_pct = self.params["net_volume_pct"]
        max_hold = self.params["max_hold_days"]

        # 連續買超天數
        is_buy = (net > 0).astype(int)
        consecutive_buy = is_buy.rolling(consecutive, min_periods=consecutive).sum()
        all_consecutive = consecutive_buy >= consecutive

        # 多券商共買
        enough_brokers = broker_count >= min_brokers

        # 累積淨買超佔日均量比例
        cumulative_net = net.rolling(consecutive, min_periods=consecutive).sum()
        if "volume" in df.columns:
            avg_vol = df["volume"].rolling(20, min_periods=5).mean().fillna(
                df["volume"]
            )
            volume_ok = cumulative_net > avg_vol * net_vol_pct
        else:
            volume_ok = pd.Series(True, index=df.index)

        # 買入訊號
        buy = all_consecutive & enough_brokers & volume_ok

        # 賣出：外資連續 3 天賣超
        is_sell = (net < 0).astype(int)
        consecutive_sell = is_sell.rolling(3, min_periods=3).sum()
        sell = consecutive_sell >= 3

        signal = pd.Series(0, index=df.index)
        signal[buy] = 1
        signal[sell] = -1

        # 最大持有天數強制出場
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
