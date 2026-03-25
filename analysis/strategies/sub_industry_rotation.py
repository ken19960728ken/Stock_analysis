"""次產業輪動策略 — 按次產業營收動能+法人流向排名，買入強勢次產業股票"""

import numpy as np
import pandas as pd

from analysis.strategies.base import Strategy


class SubIndustryRotationStrategy(Strategy):
    name = "次產業輪動"
    description = "按次產業營收動能+法人流向排名，買入強勢次產業龍頭股"
    params = {
        "lookback_months": 3,
        "lookback_days": 20,
        "top_n_industries": 3,
        "momentum_weight": 0.5,
        "flow_weight": 0.5,
        "max_hold_days": 60,
    }

    # 類別層級快取：月度產業排名（避免每支股票重複計算）
    _cached_rankings = None
    _cached_key = None

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["signal"] = 0

        top_n = self.params["top_n_industries"]
        max_hold = self.params["max_hold_days"]

        # 需要 sub_industry 欄位（由 enrich_data merge 進來）
        if "sub_industry" not in df.columns or df["sub_industry"].isna().all():
            return df

        stock_sub = df["sub_industry"].dropna().iloc[0] if df["sub_industry"].notna().any() else None
        if stock_sub is None:
            return df

        # 需要營收資料判斷產業動能
        if "revenue" not in df.columns:
            return df

        # 用營收 YoY 趨勢 + 法人流向判斷次產業動能
        # 找出營收 YoY 欄位（動態搜尋）
        yoy_col = None
        for c in df.columns:
            if c.lower() in ("revenue_yoy", "month_revenue_year_on_year"):
                yoy_col = c
                break
        if yoy_col is None:
            return df

        yoy = pd.to_numeric(df[yoy_col], errors="coerce").ffill()

        # 營收 YoY 加速趨勢（近期 > 前期）
        yoy_accel = yoy > yoy.shift(21)  # 月度比較
        yoy_strong = yoy > 10  # 營收 YoY > 10%

        # 法人流向（若有資料）
        has_inst = "institutional_net_buy" in df.columns
        if has_inst:
            inst = pd.to_numeric(df["institutional_net_buy"], errors="coerce").fillna(0)
            inst_positive = inst.rolling(5, min_periods=1).sum() > 0
            # 買入條件：營收 YoY 強勢 + (加速趨勢 或 法人買超)
            buy = yoy_strong & (yoy_accel | inst_positive)
            # 賣出條件：營收 YoY 轉負 且 法人未買超
            sell = (yoy < 0) & (~inst_positive)
        else:
            # 無法人資料：營收 YoY 強勢 + 加速趨勢
            buy = yoy_strong & yoy_accel
            sell = yoy < 0

        # 建立訊號
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
        """狀態機：強制出場邏輯"""
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
