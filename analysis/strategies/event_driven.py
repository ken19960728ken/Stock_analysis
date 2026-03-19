"""
事件驅動策略 — 除息後折價買入，等待填息獲利

改進原理：
- 原始策略在除息前買入、除息後賣出 → 買在高點賣在低點（除息扣股價）
- 修正為除息後買入（折價進場），持有 60 天等待填息
- 新增殖利率門檻過濾，避免買入小配息股
"""

import pandas as pd

from analysis.strategies.base import Strategy


class EventDrivenStrategy(Strategy):
    name = "事件驅動"
    description = "除息後折價買入，等待填息獲利"
    params = {
        "event_type": "dividend",
        "entry_days_after": 3,       # 除息日後 N 天買入（等價格穩定）
        "exit_days_after": 60,       # 持有天數（填息通常需 1-2 個月）
        "min_dividend_yield": 2.0,   # 最低殖利率門檻（%）
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

        # 簡化邏輯：如果有 dividend 欄位，在除息日後買入、持有至填息
        if "dividend" in df.columns:
            df = df.reset_index(drop=True)
            df["signal"] = 0
            entry_after = self.params.get("entry_days_after", 3)
            exit_after = self.params.get("exit_days_after", 60)
            min_yield = self.params.get("min_dividend_yield", 2.0)

            dividend_positions = df.index[df["dividend"] > 0].tolist()
            last_exit_pos = -1

            for pos in dividend_positions:
                # 殖利率過濾：dividend / 前一日 close * 100（除息日收盤已扣股利）
                prev_close = df["close"].iloc[pos - 1] if pos > 0 else None
                if prev_close is not None and prev_close > 0:
                    div_yield = df["dividend"].iloc[pos] / prev_close * 100
                    if div_yield < min_yield:
                        continue

                entry_pos = min(len(df) - 1, pos + entry_after)
                exit_pos = min(len(df) - 1, pos + exit_after)

                if entry_pos <= last_exit_pos:
                    continue
                if entry_pos >= exit_pos:
                    continue

                df.iloc[entry_pos, df.columns.get_loc("signal")] = 1
                df.iloc[exit_pos, df.columns.get_loc("signal")] = -1
                last_exit_pos = exit_pos
        else:
            df["signal"] = 0

        return df
