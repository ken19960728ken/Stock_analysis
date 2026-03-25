"""營收動能策略 — 營收 YoY 加速成長 + 營收創新高 + PE 估值過濾"""

import numpy as np
import pandas as pd

from analysis.strategies.base import Strategy


class RevenueMomentumStrategy(Strategy):
    name = "營收動能"
    description = "營收 YoY 加速成長 + 營收創新高 + PE 估值過濾"
    params = {
        "yoy_threshold": 15.0,        # YoY 最低門檻（20→15%，涵蓋更多成長股）
        "acceleration_months": 2,      # 連續加速月數（3→2，降低嚴格度）
        "pe_upper_limit": 60.0,        # PE 上限（40→60，不排除高成長龍頭）
        "enable_pe_filter": True,      # 是否啟用 PE 過濾
        "max_holding_days": 180,       # 最大持有天數（120→180，讓趨勢跑更久）
        "yoy_exit_threshold": 5.0,     # YoY 低於此值觸發賣出（10→5%，更寬容）
    }

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        yoy_thr = self.params["yoy_threshold"]
        accel_m = self.params["acceleration_months"]
        pe_upper = self.params["pe_upper_limit"]
        enable_pe = self.params["enable_pe_filter"]
        max_hold = self.params["max_holding_days"]
        yoy_exit_thr = self.params["yoy_exit_threshold"]

        df["signal"] = 0

        # 需要營收資料（由 enrich_data merge 進來）
        if "revenue" not in df.columns:
            return df

        has_rev_month = "revenue_month" in df.columns
        has_rev_year = "revenue_year" in df.columns

        # ─── 計算營收 YoY ───
        if "revenue_yoy" not in df.columns:
            if not (has_rev_month and has_rev_year):
                return df

            # 建立月營收查找表（去重，取每個 year-month 的最新值）
            rev_df = df.dropna(subset=["revenue", "revenue_month", "revenue_year"]).copy()
            rev_df = rev_df.drop_duplicates(subset=["revenue_year", "revenue_month"], keep="last")

            # 建立 (year, month) -> revenue 的查找表
            prev_map = rev_df.set_index(["revenue_year", "revenue_month"])["revenue"].to_dict()

            # 向量化計算 YoY
            prev_year = df["revenue_year"] - 1
            prev_keys = list(zip(prev_year, df["revenue_month"]))
            prev_rev = pd.Series(
                [prev_map.get(k) for k in prev_keys],
                index=df.index, dtype=float,
            )
            mask = prev_rev.notna() & (prev_rev > 0) & df["revenue"].notna()
            df["revenue_yoy"] = np.nan
            df.loc[mask, "revenue_yoy"] = (
                (df.loc[mask, "revenue"].astype(float) / prev_rev.loc[mask] - 1) * 100
            )

        # ─── 填充（月度資料，每日前向填充）───
        yoy_filled = df["revenue_yoy"].astype(float).ffill()
        rev_filled = df["revenue"].astype(float).ffill()

        # ─── 營收 6 個月 rolling max / min（排除當期，避免自含偏差）───
        df["rev_6m_max"] = rev_filled.shift(1).rolling(window=126, min_periods=10).max()
        df["rev_6m_min"] = rev_filled.shift(1).rolling(window=126, min_periods=10).min()

        # ─── YoY 加速（向量化）───
        yoy_increasing = pd.Series(True, index=df.index)
        if accel_m >= 2:
            step = 21  # 約 1 個月交易日
            for lag in range(1, accel_m):
                yoy_increasing = yoy_increasing & (
                    yoy_filled > yoy_filled.shift(lag * step)
                )
            yoy_increasing = yoy_increasing.fillna(False)

        # ─── 買入條件 ───
        buy = (
            (yoy_filled > yoy_thr) &
            (rev_filled >= df["rev_6m_max"]) &
            yoy_increasing
        )

        # PE 過濾（估值不能過高）— 動態搜尋欄位名稱
        per_col = None
        for c in df.columns:
            if c.lower() in ("per", "pe_ratio", "pe", "本益比"):
                per_col = c
                break
        if enable_pe and per_col:
            per = df[per_col].astype(float).ffill()
            pe_ok = (per > 0) & (per < pe_upper)
            buy = buy & pe_ok

        # ─── 賣出條件 ───
        yoy_exit = yoy_filled < yoy_exit_thr
        rev_below_min = rev_filled < df["rev_6m_min"]
        sell_base = yoy_exit | rev_below_min

        # ─── 最大持有天數強制出場（向量化狀態機）───
        signal = pd.Series(0, index=df.index)
        signal[buy] = 1
        signal[sell_base] = -1

        if max_hold > 0:
            final_signal = self._apply_max_hold(signal, max_hold)
            df["signal"] = final_signal
        else:
            df["signal"] = signal

        return df

    @staticmethod
    def _apply_max_hold(signal: pd.Series, max_hold: int) -> pd.Series:
        """狀態機：強制出場邏輯（向量化友好版）"""
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
