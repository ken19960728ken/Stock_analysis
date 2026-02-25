"""
事件研究引擎 — 除息、財報公布日等事件的異常報酬分析
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class EventStudyResult:
    event_type: str = ""
    events: pd.DataFrame = field(default_factory=pd.DataFrame)
    car: pd.DataFrame = field(default_factory=pd.DataFrame)  # [day_offset, car, t_stat]
    aar: pd.DataFrame = field(default_factory=pd.DataFrame)  # [day_offset, aar]
    stats: dict = field(default_factory=dict)


def extract_events(
    event_source: pd.DataFrame,
    event_type: str = "dividend",
) -> pd.DataFrame:
    """
    從資料中提取事件

    Parameters:
        event_source: 事件來源資料
        event_type: "dividend" | "earnings"

    Returns:
        DataFrame[stock_id, event_date, event_value]
    """
    if event_source.empty:
        return pd.DataFrame(columns=["stock_id", "event_date", "event_value"])

    df = event_source.copy()
    df["date"] = pd.to_datetime(df["date"])

    if event_type == "dividend":
        value_col = "dividend" if "dividend" in df.columns else None
        result = df[["stock_id", "date"]].copy()
        result.rename(columns={"date": "event_date"}, inplace=True)
        if value_col:
            result["event_value"] = pd.to_numeric(df[value_col], errors="coerce")
        else:
            result["event_value"] = 1.0
    elif event_type == "earnings":
        result = df[["stock_id", "date"]].copy()
        result.rename(columns={"date": "event_date"}, inplace=True)
        if "eps_value" in df.columns:
            result["event_value"] = pd.to_numeric(df["eps_value"], errors="coerce")
        elif "value" in df.columns:
            result["event_value"] = pd.to_numeric(df["value"], errors="coerce")
        else:
            result["event_value"] = 1.0
    else:
        raise ValueError(f"Unknown event_type: {event_type}")

    return result.dropna(subset=["event_date"]).reset_index(drop=True)


def calc_abnormal_returns(
    price_df: pd.DataFrame,
    events: pd.DataFrame,
    window_before: int = 10,
    window_after: int = 20,
    estimation_window: int = 120,
    model: str = "market_adjusted",
) -> EventStudyResult:
    """
    計算事件窗口的異常報酬

    Parameters:
        price_df: 日K資料 (stock_id, date, close)
        events: 事件清單 (stock_id, event_date, event_value)
        window_before: 事件前窗口天數
        window_after: 事件後窗口天數
        estimation_window: 估計窗口天數（用於正常報酬估計）
        model: "market_adjusted" | "mean_return"

    Returns:
        EventStudyResult
    """
    if price_df.empty or events.empty:
        return EventStudyResult()

    price_df = price_df.copy()
    price_df["date"] = pd.to_datetime(price_df["date"])
    events = events.copy()
    events["event_date"] = pd.to_datetime(events["event_date"])

    # 計算各股日報酬率
    price_df = price_df.sort_values(["stock_id", "date"])
    price_df["return"] = price_df.groupby("stock_id")["close"].pct_change()

    # 市場報酬率（等權平均）
    if model == "market_adjusted":
        market_return = price_df.groupby("date")["return"].mean()

    all_ar_windows = []  # 收集所有事件的 AR 窗口

    for _, event in events.iterrows():
        sid = event["stock_id"]
        edate = event["event_date"]

        stock_prices = price_df[price_df["stock_id"] == sid].copy()
        if stock_prices.empty:
            continue

        stock_prices = stock_prices.set_index("date").sort_index()

        # 找到事件日在價格序列中的位置
        trading_dates = stock_prices.index
        if edate not in trading_dates:
            # 找最近的交易日
            after_dates = trading_dates[trading_dates >= edate]
            if after_dates.empty:
                continue
            edate = after_dates[0]

        event_idx = trading_dates.get_loc(edate)
        start_idx = max(0, event_idx - window_before)
        end_idx = min(len(trading_dates) - 1, event_idx + window_after)

        if event_idx - start_idx < window_before // 2:
            continue

        # 計算異常報酬
        window_returns = stock_prices.iloc[start_idx:end_idx + 1]["return"].values

        if model == "mean_return":
            est_start = max(0, event_idx - window_before - estimation_window)
            est_end = event_idx - window_before
            est_returns = stock_prices.iloc[est_start:est_end]["return"].dropna()
            normal_return = est_returns.mean() if len(est_returns) > 10 else 0.0
            ar = window_returns - normal_return
        else:  # market_adjusted
            window_dates = stock_prices.iloc[start_idx:end_idx + 1].index
            market_r = market_return.reindex(window_dates).fillna(0).values
            ar = window_returns - market_r

        # 對齊 day_offset
        day_offsets = list(range(-(event_idx - start_idx), end_idx - event_idx + 1))
        if len(day_offsets) != len(ar):
            min_len = min(len(day_offsets), len(ar))
            day_offsets = day_offsets[:min_len]
            ar = ar[:min_len]

        ar_series = pd.Series(ar, index=day_offsets, name=sid)
        all_ar_windows.append(ar_series)

    if not all_ar_windows:
        return EventStudyResult(events=events, stats={"n_events": 0})

    # 統計平均異常報酬 (AAR) 和累積異常報酬 (CAR)
    ar_matrix = pd.DataFrame(all_ar_windows)

    # AAR: 每個 day_offset 的平均 AR
    aar_values = ar_matrix.mean(axis=0).dropna()
    aar_df = pd.DataFrame({
        "day_offset": aar_values.index,
        "aar": aar_values.values,
    })

    # CAR
    car_values = aar_values.cumsum()
    n_events = ar_matrix.count(axis=0)
    ar_std = ar_matrix.std(axis=0).replace(0, np.nan)
    t_stat = aar_values / (ar_std / np.sqrt(n_events))

    car_df = pd.DataFrame({
        "day_offset": car_values.index,
        "car": car_values.values,
        "t_stat": t_stat.reindex(car_values.index).values,
    })

    # 統計
    stats = {
        "n_events": len(all_ar_windows),
        "car_total": float(car_values.iloc[-1]) if not car_values.empty else 0.0,
        "aar_mean": float(aar_values.mean()),
        "aar_positive_ratio": float((aar_values > 0).mean()),
        "significant_days": int((t_stat.abs() > 1.96).sum()),
    }

    return EventStudyResult(
        event_type="event",
        events=events,
        car=car_df,
        aar=aar_df,
        stats=stats,
    )


def event_trading_signals(
    events: pd.DataFrame,
    price_df: pd.DataFrame,
    entry_before: int = 5,
    exit_after: int = 10,
) -> pd.DataFrame:
    """
    產生事件驅動的交易訊號

    Parameters:
        events: (stock_id, event_date, event_value)
        price_df: 日K (stock_id, date, close, ...)
        entry_before: 事件前 N 天買入
        exit_after: 事件後 N 天賣出

    Returns:
        price_df 加上 signal 欄位 (1=買, -1=賣, 0=無)
    """
    if events.empty or price_df.empty:
        df = price_df.copy()
        df["signal"] = 0
        return df

    price_df = price_df.copy()
    price_df["date"] = pd.to_datetime(price_df["date"])
    events = events.copy()
    events["event_date"] = pd.to_datetime(events["event_date"])

    price_df["signal"] = 0

    for _, event in events.iterrows():
        sid = event["stock_id"]
        edate = event["event_date"]

        mask = price_df["stock_id"] == sid
        stock_dates = price_df.loc[mask, "date"]
        if stock_dates.empty:
            continue

        # 買入：事件前 entry_before 天
        entry_date = edate - pd.Timedelta(days=entry_before)
        entry_mask = mask & (price_df["date"] >= entry_date) & (price_df["date"] < edate)
        first_entry = price_df.loc[entry_mask].head(1).index
        if len(first_entry) > 0:
            price_df.loc[first_entry[0], "signal"] = 1

        # 賣出：事件後 exit_after 天
        exit_date = edate + pd.Timedelta(days=exit_after)
        exit_mask = mask & (price_df["date"] > edate) & (price_df["date"] <= exit_date)
        last_exit = price_df.loc[exit_mask].tail(1).index
        if len(last_exit) > 0:
            price_df.loc[last_exit[0], "signal"] = -1

    return price_df
