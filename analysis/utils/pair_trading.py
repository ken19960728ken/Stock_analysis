"""
配對交易工具 — Engle-Granger 共整合、Z-Score、半衰期
"""

import numpy as np
import pandas as pd
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant
from statsmodels.tsa.stattools import adfuller


def engle_granger_test(y: pd.Series, x: pd.Series) -> dict:
    """
    Engle-Granger 兩步法共整合檢定

    Returns:
        dict with keys: beta, intercept, adf_stat, p_value, critical_values,
                        is_cointegrated, residuals
    """
    result = {}

    # Step 1: OLS 迴歸
    x_const = add_constant(x.values)
    model = OLS(y.values, x_const).fit()
    result["beta"] = float(model.params[1])
    result["intercept"] = float(model.params[0])
    result["r_squared"] = float(model.rsquared)

    # 殘差
    residuals = y.values - (model.params[0] + model.params[1] * x.values)
    result["residuals"] = pd.Series(residuals, index=y.index)

    # Step 2: ADF 檢定殘差
    adf = adfuller(residuals, maxlag=1)
    result["adf_stat"] = float(adf[0])
    result["p_value"] = float(adf[1])
    result["critical_values"] = {k: float(v) for k, v in adf[4].items()}
    result["is_cointegrated"] = adf[1] < 0.05

    return result


def calc_spread(y: pd.Series, x: pd.Series, beta: float, intercept: float) -> pd.Series:
    """計算價差 (Spread)"""
    return y - (beta * x + intercept)


def calc_zscore(spread: pd.Series, window: int = 20) -> pd.Series:
    """計算 Z-Score"""
    mean = spread.rolling(window).mean()
    std = spread.rolling(window).std()
    return (spread - mean) / std


def calc_half_life(spread: pd.Series) -> float:
    """計算半衰期 (Ornstein-Uhlenbeck)"""
    spread_lag = spread.shift(1).dropna()
    spread_diff = spread.diff().dropna()

    aligned = pd.concat([spread_diff, spread_lag], axis=1).dropna()
    if len(aligned) < 3:
        return float("inf")

    y = aligned.iloc[:, 0].values
    x = add_constant(aligned.iloc[:, 1].values)
    model = OLS(y, x).fit()
    theta = model.params[1]

    if theta >= 0:
        return float("inf")  # 非均值回歸
    return float(-np.log(2) / theta)


def find_cointegrated_pairs(price_dict: dict, threshold: float = 0.05) -> list:
    """
    從一組股票中找出共整合配對

    Parameters:
        price_dict: {stock_id: close_price_series}
        threshold: p-value 門檻

    Returns:
        list of dicts: [{stock_a, stock_b, p_value, beta, half_life}, ...]
    """
    ids = list(price_dict.keys())
    pairs = []

    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            try:
                y = price_dict[ids[i]]
                x = price_dict[ids[j]]
                aligned = pd.concat([y, x], axis=1).dropna()
                if len(aligned) < 60:
                    continue

                y_aligned = aligned.iloc[:, 0]
                x_aligned = aligned.iloc[:, 1]

                result = engle_granger_test(y_aligned, x_aligned)
                if result["p_value"] < threshold:
                    spread = calc_spread(y_aligned, x_aligned,
                                         result["beta"], result["intercept"])
                    hl = calc_half_life(spread)
                    pairs.append({
                        "stock_a": ids[i],
                        "stock_b": ids[j],
                        "p_value": round(result["p_value"], 4),
                        "beta": round(result["beta"], 4),
                        "half_life": round(hl, 1),
                        "r_squared": round(result["r_squared"], 4),
                    })
            except Exception:
                continue

    pairs.sort(key=lambda x: x["p_value"])
    return pairs


def pair_trading_signals(
    spread: pd.Series,
    entry_z: float = 2.0,
    exit_z: float = 0.5,
    stop_z: float = 3.5,
    window: int = 20,
) -> pd.Series:
    """
    配對交易訊號

    Returns:
        Series of signals:
          1 = 做多價差 (買Y賣X)
         -1 = 做空價差 (賣Y買X)
          0 = 無部位/平倉
    """
    zscore = calc_zscore(spread, window)
    signals = pd.Series(0, index=spread.index)
    position = 0

    for i in range(len(zscore)):
        z = zscore.iloc[i]
        if np.isnan(z):
            continue

        if position == 0:
            if z < -entry_z:
                position = 1   # 價差低於均值，做多價差
            elif z > entry_z:
                position = -1  # 價差高於均值，做空價差
        elif position == 1:
            if z > -exit_z or z < -stop_z:
                position = 0   # 回歸或停損
        elif position == -1:
            if z < exit_z or z > stop_z:
                position = 0

        signals.iloc[i] = position

    return signals
