"""
因子工程工具模組 — Z-Score 標準化、IC 計算、因子相關性
純計算工具，不依賴 Streamlit
"""

import numpy as np
import pandas as pd
from scipy import stats


def zscore_normalize(series: pd.Series, window: int = 252,
                     min_periods: int = 60) -> pd.Series:
    """Z-Score 標準化（單股時序，rolling 模式避免前視偏差）。

    使用 rolling 窗口計算均值和標準差，確保每個時間點只使用
    過去的資料進行標準化。Winsorize 到 [-3, 3]。

    Parameters
    ----------
    series : pd.Series
        原始因子值
    window : int
        rolling 窗口大小（預設 252 = 一年交易日）
    min_periods : int
        最少需要的觀測值（預設 60 = 約三個月）
    """
    if series.dropna().empty or len(series.dropna()) <= 1:
        return pd.Series(0.0, index=series.index)

    rolling_mean = series.rolling(window=window, min_periods=min_periods).mean()
    rolling_std = series.rolling(window=window, min_periods=min_periods).std()

    # 避免除以零
    safe_std = rolling_std.replace(0, np.nan)
    z = (series - rolling_mean) / safe_std

    return z.clip(-3, 3)


def zscore_cross_sectional(df: pd.DataFrame, factor_col: str) -> pd.Series:
    """跨股票截面 Z-Score（groupby date）"""
    def _zscore_group(group):
        vals = group[factor_col]
        s = vals.dropna()
        if len(s) <= 1 or s.std() == 0:
            return pd.Series(0.0, index=group.index)
        mean = s.mean()
        std = s.std()
        z = (vals - mean) / std
        return z.clip(-3, 3)

    return df.groupby("date", group_keys=False).apply(_zscore_group, include_groups=False)


def calculate_ic(factor_values: pd.Series, forward_returns: pd.Series,
                 method: str = "spearman") -> float:
    """計算 Information Coefficient（因子值 vs 未來報酬的 rank correlation）"""
    mask = factor_values.notna() & forward_returns.notna()
    fv = factor_values[mask]
    fr = forward_returns[mask]

    if len(fv) < 3:
        return float("nan")

    if method == "spearman":
        corr, _ = stats.spearmanr(fv, fr)
    elif method == "pearson":
        corr, _ = stats.pearsonr(fv, fr)
    else:
        raise ValueError(f"Unknown method: {method}")

    return float(corr)


def ic_series(factor_df: pd.DataFrame, return_df: pd.DataFrame,
              factor_col: str, forward_days: int = 5) -> pd.DataFrame:
    """滾動 IC 時間序列。回傳 [date, ic, ic_cumsum]"""
    merged = factor_df.merge(return_df, on=["date", "stock_id"], suffixes=("", "_ret"))

    # 計算前瞻報酬
    if "close" in merged.columns and "close_ret" not in merged.columns:
        merged = merged.sort_values(["stock_id", "date"])
        merged["forward_return"] = merged.groupby("stock_id")["close"].transform(
            lambda x: x.shift(-forward_days) / x - 1
        )
    elif "close_ret" in merged.columns:
        merged = merged.sort_values(["stock_id", "date"])
        merged["forward_return"] = merged.groupby("stock_id")["close_ret"].transform(
            lambda x: x.shift(-forward_days) / x - 1
        )

    results = []
    for date, group in merged.groupby("date"):
        fv = group[factor_col]
        fr = group["forward_return"]
        ic_val = calculate_ic(fv, fr, method="spearman")
        results.append({"date": date, "ic": ic_val})

    result_df = pd.DataFrame(results)
    if not result_df.empty:
        result_df["ic_cumsum"] = result_df["ic"].cumsum()
    else:
        result_df["ic_cumsum"] = []

    return result_df


def rolling_ic_mean(ic_df: pd.DataFrame, window: int = 60) -> pd.Series:
    """
    滾動 IC 均值

    Parameters:
        ic_df: DataFrame with columns [date, ic]
        window: 滾動窗口

    Returns:
        pd.Series(index=date) 滾動 IC 均值
    """
    if ic_df.empty or "ic" not in ic_df.columns:
        return pd.Series(dtype=float)
    s = ic_df.set_index("date")["ic"].dropna()
    return s.rolling(window, min_periods=max(window // 3, 5)).mean()


def zscore_industry_neutral(
    df: pd.DataFrame,
    factor_col: str,
    industry_col: str = "sector",
) -> pd.Series:
    """產業中性化 Z-Score：同日期同產業內做截面 Z-Score，消除產業偏差。

    Parameters:
        df: DataFrame，必須包含 date, stock_id, factor_col, industry_col 欄位
        factor_col: 要中性化的因子欄位名稱
        industry_col: 產業分類欄位名稱（預設 "sector"）

    Returns:
        pd.Series: 產業中性化後的 Z-Score（與 df 同 index）
    """
    if factor_col not in df.columns or industry_col not in df.columns:
        return pd.Series(0.0, index=df.index)

    def _zscore_group(group):
        vals = group[factor_col]
        s = vals.dropna()
        if len(s) <= 1 or s.std() == 0:
            return pd.Series(0.0, index=group.index)
        mean = s.mean()
        std = s.std()
        z = (vals - mean) / std
        return z.clip(-3, 3)

    return df.groupby(["date", industry_col], group_keys=False).apply(
        _zscore_group, include_groups=False
    )


def factor_correlation_matrix(factors: dict) -> pd.DataFrame:
    """多因子相關性矩陣。factors: {name: pd.Series}"""
    df = pd.DataFrame(factors)
    return df.corr()
