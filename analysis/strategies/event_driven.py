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
            df["signal"] = 0
            entry_before = self.params.get("entry_days_before", 5)
            exit_after = self.params.get("exit_days_after", 10)

            dividend_dates = df[df["dividend"] > 0].index.tolist()
            for div_idx in dividend_dates:
                pos = df.index.get_loc(div_idx)
                entry_pos = max(0, pos - entry_before)
                exit_pos = min(len(df) - 1, pos + exit_after)
                df.iloc[entry_pos, df.columns.get_loc("signal")] = 1
                df.iloc[exit_pos, df.columns.get_loc("signal")] = -1
        else:
            df["signal"] = 0

        return df
