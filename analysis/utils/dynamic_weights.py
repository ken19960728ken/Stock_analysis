"""
動態因子權重模組 — 根據滾動 IC 表現自動調整多因子權重
"""

import numpy as np
import pandas as pd


def rolling_ic_weights(
    ic_dict: dict,
    lookback: int = 60,
    min_ic: float = 0.02,
    method: str = "icir",
) -> pd.DataFrame:
    """
    依滾動 IC 表現動態計算各因子權重

    Parameters:
        ic_dict: {factor_name: DataFrame with columns [date, ic]}
        lookback: 滾動窗口天數
        min_ic: 最低 |IC| 門檻，低於此值的因子權重歸零
        method: "ic_mean" | "icir" | "ic_decay"

    Returns:
        DataFrame[date, factor_name, weight]
    """
    if not ic_dict:
        return pd.DataFrame(columns=["date", "factor_name", "weight"])

    if method == "ic_decay":
        return ic_decay_weights(ic_dict, half_life=lookback // 3)

    # 對齊所有因子的 IC 序列
    ic_frames = {}
    for name, df in ic_dict.items():
        if df.empty or "ic" not in df.columns:
            continue
        s = df.set_index("date")["ic"].dropna()
        if not s.empty:
            ic_frames[name] = s

    if not ic_frames:
        return pd.DataFrame(columns=["date", "factor_name", "weight"])

    ic_panel = pd.DataFrame(ic_frames)

    if method == "icir":
        rolling_mean = ic_panel.rolling(lookback, min_periods=max(lookback // 3, 5)).mean()
        rolling_std = ic_panel.rolling(lookback, min_periods=max(lookback // 3, 5)).std()
        rolling_std = rolling_std.replace(0, np.nan)
        raw_scores = (rolling_mean / rolling_std).abs()
    else:  # ic_mean
        raw_scores = ic_panel.rolling(lookback, min_periods=max(lookback // 3, 5)).mean().abs()

    # 低於門檻的歸零
    raw_scores = raw_scores.where(raw_scores >= min_ic, 0)

    # 行歸一化為權重
    row_sum = raw_scores.sum(axis=1)
    row_sum = row_sum.replace(0, np.nan)
    weights_wide = raw_scores.div(row_sum, axis=0).fillna(0)

    # 轉長格式
    weights_long = weights_wide.reset_index().melt(
        id_vars="date", var_name="factor_name", value_name="weight"
    )
    weights_long = weights_long.dropna(subset=["weight"])
    return weights_long


def ic_decay_weights(ic_dict: dict, half_life: int = 20) -> pd.DataFrame:
    """指數衰減加權 IC → 權重"""
    if not ic_dict:
        return pd.DataFrame(columns=["date", "factor_name", "weight"])

    ic_frames = {}
    for name, df in ic_dict.items():
        if df.empty or "ic" not in df.columns:
            continue
        s = df.set_index("date")["ic"].dropna()
        if not s.empty:
            ic_frames[name] = s

    if not ic_frames:
        return pd.DataFrame(columns=["date", "factor_name", "weight"])

    ic_panel = pd.DataFrame(ic_frames)
    decay = np.log(2) / half_life

    results = []
    dates = ic_panel.index
    for i, date in enumerate(dates):
        if i < 5:
            continue
        historical = ic_panel.iloc[:i + 1]
        n = len(historical)
        # 指數衰減權重
        time_weights = np.exp(-decay * np.arange(n - 1, -1, -1))
        weighted_ic = (historical.values * time_weights[:, None]).sum(axis=0) / time_weights.sum()
        abs_ic = np.abs(weighted_ic)
        total = abs_ic.sum()
        if total > 0:
            factor_weights = abs_ic / total
        else:
            factor_weights = np.ones(len(ic_frames)) / len(ic_frames)

        for j, name in enumerate(ic_frames.keys()):
            results.append({
                "date": date,
                "factor_name": name,
                "weight": float(factor_weights[j]),
            })

    return pd.DataFrame(results)


def combine_factor_scores(factor_scores: dict, weights: pd.Series) -> pd.Series:
    """
    加權合成多因子分數

    Parameters:
        factor_scores: {factor_name: pd.Series(index=stock_id)}
        weights: pd.Series(index=factor_name, values=weight)

    Returns:
        pd.Series(index=stock_id) 合成分數
    """
    if not factor_scores or weights.empty:
        return pd.Series(dtype=float)

    combined = None
    for name, scores in factor_scores.items():
        w = weights.get(name, 0.0)
        if w > 0:
            aligned = scores.fillna(0) * w
            if combined is None:
                combined = aligned
            else:
                combined = combined.add(aligned, fill_value=0)

    return combined if combined is not None else pd.Series(dtype=float)
