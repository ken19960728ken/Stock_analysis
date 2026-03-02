"""
事件驅動策略 — 根據除息/財報等事件產生交易訊號
"""

import pandas as pd

from analysis.strategies.base import Strategy


class EventDrivenStrategy(Strategy):
    name = "事件驅動"
    description = "根據除息/財報等事件，在事件前買入、事件後賣出"
    params = {
        "event_type": "dividend",
        "entry_days_before": 5,
        "exit_days_after": 10,
    }

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        使用預設的除息/財報事件資料生成訊號。

        如果 data 中已有 'signal' 欄位（由 event_trading_signals 注入），
        直接使用；否則使用簡化邏輯。
        """
        df = data.copy()

        if "signal" in df.columns:
            return df

        # 簡化邏輯：如果有 dividend 欄位，在除息日前買入、後賣出
        if "dividend" in df.columns:
            df = df.reset_index(drop=True)
            df["signal"] = 0
            entry_before = self.params.get("entry_days_before", 5)
            exit_after = self.params.get("exit_days_after", 10)

            dividend_positions = df.index[df["dividend"] > 0].tolist()
            last_exit_pos = -1  # 追蹤上一個事件的賣出位置，避免訊號重疊
            for pos in dividend_positions:
                entry_pos = max(0, pos - entry_before)
                exit_pos = min(len(df) - 1, pos + exit_after)
                # 若此事件的買入點在上一個事件的賣出點之前，跳過以避免衝突
                if entry_pos <= last_exit_pos:
                    continue
                df.iloc[entry_pos, df.columns.get_loc("signal")] = 1
                df.iloc[exit_pos, df.columns.get_loc("signal")] = -1
                last_exit_pos = exit_pos
        else:
            df["signal"] = 0

        return df
