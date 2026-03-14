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

        # 需要產業排名資料（由 enrich_data 提供 _industry_rank 欄位）
        if "_industry_rank" in df.columns:
            rank_filled = df["_industry_rank"].ffill()
            buy = rank_filled <= top_n
            sell = rank_filled > top_n
        else:
            # Fallback: 若有營收動能相關欄位，用簡化邏輯
            if "revenue" not in df.columns:
                return df

            # 簡化版：用營收 YoY 判斷產業動能
            if "revenue_yoy" in df.columns or "month_revenue_year_on_year" in df.columns:
                yoy_col = "revenue_yoy" if "revenue_yoy" in df.columns else "month_revenue_year_on_year"
                yoy = pd.to_numeric(df[yoy_col], errors="coerce").ffill()
                # 營收 YoY > 10% 且有法人買超 → 買入
                buy = yoy > 10
                if "institutional_net_buy" in df.columns:
                    inst = pd.to_numeric(df["institutional_net_buy"], errors="coerce").fillna(0)
                    inst_positive = inst.rolling(5, min_periods=1).sum() > 0
                    buy = buy & inst_positive
                sell = yoy < 0
            else:
                return df

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
