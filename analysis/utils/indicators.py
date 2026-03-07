"""
技術指標計算模組 — 純 pandas/numpy 實作（無外部指標庫依賴）
"""

import numpy as np
import pandas as pd


def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def add_ma(df: pd.DataFrame, periods: list = None, col: str = "close") -> pd.DataFrame:
    """添加簡單移動平均線 SMA"""
    if periods is None:
        periods = [5, 20, 60]
    for p in periods:
        df[f"MA{p}"] = _sma(df[col], p)
    return df


def add_ema(df: pd.DataFrame, periods: list = None, col: str = "close") -> pd.DataFrame:
    """添加指數移動平均線 EMA"""
    if periods is None:
        periods = [5, 20, 60]
    for p in periods:
        df[f"EMA{p}"] = _ema(df[col], p)
    return df


def add_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9,
             col: str = "close") -> pd.DataFrame:
    """MACD 指標"""
    ema_fast = _ema(df[col], fast)
    ema_slow = _ema(df[col], slow)
    df["MACD"] = ema_fast - ema_slow
    df["MACD_signal"] = _ema(df["MACD"], signal)
    df["MACD_histogram"] = df["MACD"] - df["MACD_signal"]
    return df


def add_rsi(df: pd.DataFrame, period: int = 14, col: str = "close") -> pd.DataFrame:
    """RSI 指標 (Wilder's smoothing)"""
    delta = df[col].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + rs))
    return df


def add_kd(df: pd.DataFrame, k_period: int = 9, d_period: int = 3) -> pd.DataFrame:
    """KD 隨機指標 (Stochastic Oscillator)"""
    low_min = df["low"].rolling(window=k_period, min_periods=k_period).min()
    high_max = df["high"].rolling(window=k_period, min_periods=k_period).max()
    rsv = (df["close"] - low_min) / (high_max - low_min).replace(0, np.nan) * 100
    df["K"] = rsv.ewm(com=d_period - 1, adjust=False).mean()
    df["D"] = df["K"].ewm(com=d_period - 1, adjust=False).mean()
    return df


def add_bollinger(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0,
                  col: str = "close") -> pd.DataFrame:
    """布林通道"""
    df["BB_mid"] = _sma(df[col], period)
    rolling_std = df[col].rolling(window=period, min_periods=period).std()
    df["BB_upper"] = df["BB_mid"] + std_dev * rolling_std
    df["BB_lower"] = df["BB_mid"] - std_dev * rolling_std
    bandwidth = df["BB_upper"] - df["BB_lower"]
    df["BB_bandwidth"] = bandwidth / df["BB_mid"].replace(0, np.nan)
    df["BB_pct"] = (df[col] - df["BB_lower"]) / bandwidth.replace(0, np.nan)
    return df


def add_parabolic_sar(df: pd.DataFrame, af_init: float = 0.02,
                       af_step: float = 0.02, max_af: float = 0.2) -> pd.DataFrame:
    """Parabolic SAR"""
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    n = len(close)

    sar = np.full(n, np.nan)
    sar_long = np.full(n, np.nan)
    sar_short = np.full(n, np.nan)

    if n < 2:
        df["SAR"] = sar
        return df

    # 初始化
    bull = True
    af = af_init
    ep = high[0]
    sar[0] = low[0]

    for i in range(1, n):
        if bull:
            sar[i] = sar[i - 1] + af * (ep - sar[i - 1])
            sar[i] = min(sar[i], low[i - 1])
            if i >= 2:
                sar[i] = min(sar[i], low[i - 2])

            if low[i] < sar[i]:
                bull = False
                sar[i] = ep
                ep = low[i]
                af = af_init
            else:
                if high[i] > ep:
                    ep = high[i]
                    af = min(af + af_step, max_af)
        else:
            sar[i] = sar[i - 1] + af * (ep - sar[i - 1])
            sar[i] = max(sar[i], high[i - 1])
            if i >= 2:
                sar[i] = max(sar[i], high[i - 2])

            if high[i] > sar[i]:
                bull = True
                sar[i] = ep
                ep = high[i]
                af = af_init
            else:
                if low[i] < ep:
                    ep = low[i]
                    af = min(af + af_step, max_af)

        if bull:
            sar_long[i] = sar[i]
        else:
            sar_short[i] = sar[i]

    df["SAR"] = sar
    df["SAR_long"] = sar_long
    df["SAR_short"] = sar_short
    return df


def add_heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """Heikin-Ashi 平滑 K 線"""
    ha_close = (df["open"] + df["high"] + df["low"] + df["close"]) / 4

    ha_open = pd.Series(np.nan, index=df.index)
    ha_open.iloc[0] = (df["open"].iloc[0] + df["close"].iloc[0]) / 2
    for i in range(1, len(df)):
        ha_open.iloc[i] = (ha_open.iloc[i - 1] + ha_close.iloc[i - 1]) / 2

    ha_high = pd.concat([df["high"], ha_open, ha_close], axis=1).max(axis=1)
    ha_low = pd.concat([df["low"], ha_open, ha_close], axis=1).min(axis=1)

    df["HA_open"] = ha_open
    df["HA_high"] = ha_high
    df["HA_low"] = ha_low
    df["HA_close"] = ha_close
    return df


def add_williams_r(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """威廉指標 Williams %R"""
    high_max = df["high"].rolling(window=period, min_periods=period).max()
    low_min = df["low"].rolling(window=period, min_periods=period).min()
    df["WilliamsR"] = -100 * (high_max - df["close"]) / (high_max - low_min).replace(0, np.nan)
    return df


def add_awesome_oscillator(df: pd.DataFrame, fast: int = 5, slow: int = 34) -> pd.DataFrame:
    """Awesome Oscillator"""
    midpoint = (df["high"] + df["low"]) / 2
    df["AO"] = _sma(midpoint, fast) - _sma(midpoint, slow)
    return df


def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Average True Range"""
    high_low = df["high"] - df["low"]
    high_prev_close = (df["high"] - df["close"].shift(1)).abs()
    low_prev_close = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
    df["ATR"] = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    return df


def add_obv(df: pd.DataFrame, ema_period: int = 14) -> pd.DataFrame:
    """On-Balance Volume + EMA 平滑"""
    if df.empty:
        df["OBV"] = pd.Series(dtype=float)
        df["OBV_EMA"] = pd.Series(dtype=float)
        return df
    direction = (df["close"] > df["close"].shift(1)).astype(int) * 2 - 1
    direction.iloc[0] = 0
    df["OBV"] = (df["volume"] * direction).cumsum()
    df["OBV_EMA"] = _ema(df["OBV"], ema_period)
    return df


def add_keltner(df: pd.DataFrame, period: int = 20, atr_mult: float = 1.5,
                atr_period: int = 14) -> pd.DataFrame:
    """Keltner Channel"""
    df["KC_mid"] = _ema(df["close"], period)
    # ATR 計算
    high_low = df["high"] - df["low"]
    high_pc = (df["high"] - df["close"].shift(1)).abs()
    low_pc = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([high_low, high_pc, low_pc], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / atr_period, min_periods=atr_period, adjust=False).mean()
    df["KC_upper"] = df["KC_mid"] + atr_mult * atr
    df["KC_lower"] = df["KC_mid"] - atr_mult * atr
    return df


def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """計算所有常用指標"""
    if df.empty:
        return df
    df = df.copy()
    df = add_ma(df)
    df = add_macd(df)
    df = add_rsi(df)
    df = add_kd(df)
    df = add_bollinger(df)
    df = add_parabolic_sar(df)
    df = add_heikin_ashi(df)
    df = add_williams_r(df)
    df = add_awesome_oscillator(df)
    df = add_atr(df)
    return df
