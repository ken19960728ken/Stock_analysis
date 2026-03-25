"""
訊號分析工具 — 訊號衰減 + 樣本外驗證 + 擁擠度

學理來源:
- Jegadeesh & Titman (1993) "Returns to Buying Winners and Selling Losers"
- White (2000) "A Reality Check for Data Snooping"
"""

import numpy as np
import pandas as pd

from analysis.strategies.base import Strategy
from analysis.utils.backtester import Backtester


def signal_decay_report(
    strategy: Strategy,
    data: pd.DataFrame,
    horizons: list[int] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """對策略每次 signal=1，計算後續 T+N 日報酬

    學理: Jegadeesh & Titman (1993) "Returns to Buying Winners and Selling Losers"

    Returns:
        (detail_df, summary_df)
        detail_df columns: signal_date, close, ret_t1, ret_t5, ret_t10, ret_t20, ret_t60
        summary_df columns: horizon, mean_return, median_return, hit_rate, count, std
    """
    if horizons is None:
        horizons = [1, 5, 10, 20, 60]

    df = strategy.generate_signals(data.copy())

    if "signal" not in df.columns:
        empty_detail = pd.DataFrame()
        empty_summary = pd.DataFrame()
        return empty_detail, empty_summary

    signal_mask = df["signal"] == 1
    signal_indices = df.index[signal_mask].tolist()

    if not signal_indices:
        empty_detail = pd.DataFrame()
        empty_summary = pd.DataFrame()
        return empty_detail, empty_summary

    # 取得 positional indices
    iloc_positions = [df.index.get_loc(idx) for idx in signal_indices]

    records = []
    closes = df["close"].values
    dates = df["date"].values if "date" in df.columns else df.index.values

    for pos in iloc_positions:
        entry_close = closes[pos]
        row = {
            "signal_date": dates[pos],
            "close": entry_close,
        }
        for h in horizons:
            col_name = f"ret_t{h}"
            future_pos = pos + h
            if future_pos < len(closes):
                row[col_name] = (closes[future_pos] - entry_close) / entry_close
            else:
                row[col_name] = np.nan
        records.append(row)

    detail_df = pd.DataFrame(records)

    # summary 聚合
    summary_records = []
    for h in horizons:
        col = f"ret_t{h}"
        if col not in detail_df.columns:
            continue
        vals = detail_df[col].dropna()
        if len(vals) == 0:
            summary_records.append({
                "horizon": h,
                "mean_return": np.nan,
                "median_return": np.nan,
                "hit_rate": np.nan,
                "count": 0,
                "std": np.nan,
            })
        else:
            summary_records.append({
                "horizon": h,
                "mean_return": vals.mean(),
                "median_return": vals.median(),
                "hit_rate": (vals > 0).sum() / len(vals),
                "count": len(vals),
                "std": vals.std(),
            })

    summary_df = pd.DataFrame(summary_records)
    return detail_df, summary_df


def oos_validation(
    strategy: Strategy,
    data: pd.DataFrame,
    split_ratio: float = 0.7,
    capital: float = 1_000_000,
) -> dict:
    """將資料前 70% 為 in-sample、後 30% 為 out-of-sample，比較績效落差

    學理: White (2000) "A Reality Check for Data Snooping"

    Returns: dict with keys:
        is_sharpe, oos_sharpe, is_return, oos_return,
        is_win_rate, oos_win_rate, is_trades, oos_trades,
        is_period, oos_period, decay_rate, verdict
    """
    split_idx = int(len(data) * split_ratio)
    is_data = data.iloc[:split_idx].copy().reset_index(drop=True)
    oos_data = data.iloc[split_idx:].copy().reset_index(drop=True)

    bt_is = Backtester(strategy, capital=capital)
    bt_oos = Backtester(strategy, capital=capital)

    result_is = bt_is.run(is_data)
    result_oos = bt_oos.run(oos_data)

    is_sharpe = result_is.sharpe_ratio
    oos_sharpe = result_oos.sharpe_ratio

    # decay_rate: is_sharpe <= 0 時特殊處理
    if is_sharpe <= 0:
        if oos_sharpe <= is_sharpe:
            decay_rate = 1.0
        else:
            decay_rate = 0.0
    else:
        decay_rate = 1.0 - (oos_sharpe / is_sharpe)

    # verdict
    if decay_rate < 0.2:
        verdict = "stable"
    elif decay_rate < 0.5:
        verdict = "moderate"
    elif decay_rate < 0.8:
        verdict = "severe"
    else:
        verdict = "overfitting"

    # period 格式
    def _get_period(segment: pd.DataFrame) -> str:
        if "date" in segment.columns and len(segment) > 0:
            start = str(segment["date"].iloc[0])[:10]
            end = str(segment["date"].iloc[-1])[:10]
            return f"{start} ~ {end}"
        return "N/A"

    return {
        "is_sharpe": is_sharpe,
        "oos_sharpe": oos_sharpe,
        "is_return": result_is.total_return,
        "oos_return": result_oos.total_return,
        "is_win_rate": result_is.win_rate,
        "oos_win_rate": result_oos.win_rate,
        "is_trades": result_is.trade_count,
        "oos_trades": result_oos.trade_count,
        "is_period": _get_period(is_data),
        "oos_period": _get_period(oos_data),
        "decay_rate": decay_rate,
        "verdict": verdict,
    }


def signal_crowding_analysis(
    strategies: list[Strategy],
    data: pd.DataFrame,
) -> pd.DataFrame:
    """計算每天有多少策略同時發出同方向訊號

    Returns: DataFrame
        columns: date, agree_buy, agree_sell, total_strategies,
                 agreement_ratio, crowding_level
    """
    total = len(strategies)
    if total == 0:
        return pd.DataFrame()

    # 收集每個策略的 signal
    signal_matrix = pd.DataFrame()
    for i, strat in enumerate(strategies):
        sig_df = strat.generate_signals(data.copy())
        col_name = f"sig_{i}"
        if "signal" in sig_df.columns:
            signal_matrix[col_name] = sig_df["signal"].values
        else:
            signal_matrix[col_name] = 0

    # date column
    if "date" in data.columns:
        dates = data["date"].values
    else:
        dates = data.index.values

    sig_cols = [c for c in signal_matrix.columns if c.startswith("sig_")]
    sig_values = signal_matrix[sig_cols].values

    agree_buy = (sig_values == 1).sum(axis=1)
    agree_sell = (sig_values == -1).sum(axis=1)
    agreement_ratio = np.maximum(agree_buy, agree_sell) / total

    crowding_levels = []
    for ratio in agreement_ratio:
        if ratio > 0.7:
            crowding_levels.append("high")
        elif ratio >= 0.3:
            crowding_levels.append("medium")
        else:
            crowding_levels.append("low")

    result = pd.DataFrame({
        "date": dates[:len(agree_buy)],
        "agree_buy": agree_buy,
        "agree_sell": agree_sell,
        "total_strategies": total,
        "agreement_ratio": agreement_ratio,
        "crowding_level": crowding_levels,
    })
    return result


def crowding_backtest(
    strategies: list[Strategy],
    data: pd.DataFrame,
    horizons: list[int] | None = None,
) -> pd.DataFrame:
    """驗證高/低擁擠度的後續表現

    Returns: DataFrame
        columns: crowding_level, horizon, mean_return, median_return, count
    """
    if horizons is None:
        horizons = [1, 5, 10, 20, 60]

    crowding_df = signal_crowding_analysis(strategies, data)
    if crowding_df.empty:
        return pd.DataFrame()

    closes = data["close"].values
    records = []

    for level in ["low", "medium", "high"]:
        # 篩選：該 crowding_level 且 agree_buy > agree_sell
        mask = (crowding_df["crowding_level"] == level) & (
            crowding_df["agree_buy"] > crowding_df["agree_sell"]
        )
        positions = np.where(mask.values)[0]

        for h in horizons:
            rets = []
            for pos in positions:
                future_pos = pos + h
                if future_pos < len(closes):
                    ret = (closes[future_pos] - closes[pos]) / closes[pos]
                    rets.append(ret)

            if rets:
                records.append({
                    "crowding_level": level,
                    "horizon": h,
                    "mean_return": np.mean(rets),
                    "median_return": np.median(rets),
                    "count": len(rets),
                })
            else:
                records.append({
                    "crowding_level": level,
                    "horizon": h,
                    "mean_return": np.nan,
                    "median_return": np.nan,
                    "count": 0,
                })

    return pd.DataFrame(records)
