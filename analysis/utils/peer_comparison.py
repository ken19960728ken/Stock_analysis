"""
同業比較分析工具 — 找出同次產業（或同大類）股票，計算排名與百分位
"""

import numpy as np
import pandas as pd


def get_peers(
    stock_id: str,
    industry_map: pd.DataFrame,
    level: str = "sub_industry",
) -> list[str]:
    """找出同次產業（或同大類）的所有股票（含自己）

    Parameters:
        stock_id: 目標股票代碼
        industry_map: load_industry_mapping() 的回傳值
                      欄位: stock_id, sector, sub_industry, industry_category
        level: "sub_industry" 或 "sector"

    Returns:
        同業股票代碼列表（含 stock_id 自身）
    """
    if industry_map.empty or stock_id not in industry_map["stock_id"].values:
        return [stock_id]

    row = industry_map[industry_map["stock_id"] == stock_id].iloc[0]

    if level == "sub_industry" and "sub_industry" in industry_map.columns:
        sub = row.get("sub_industry")
        if pd.notna(sub):
            peers = industry_map[industry_map["sub_industry"] == sub]["stock_id"].tolist()
            if peers:
                return peers

    # Fallback to sector
    col = "sector" if "sector" in industry_map.columns else "industry_category"
    sector = row.get(col)
    if pd.notna(sector):
        peers = industry_map[industry_map[col] == sector]["stock_id"].tolist()
        if peers:
            return peers

    return [stock_id]


def calc_peer_metrics(
    stock_id: str,
    peers: list[str],
    per_df: pd.DataFrame,
    revenue_df: pd.DataFrame,
    price_df: pd.DataFrame,
    inst_df: pd.DataFrame,
    stock_names: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """計算同業指標比較表

    Parameters:
        stock_id: 目標股票代碼
        peers: 同業股票列表
        per_df: load_latest_per_all() 回傳值 (stock_id, per, pbr, dividend_yield)
        revenue_df: load_latest_revenue_all() 回傳值 (stock_id, revenue, month_revenue_year_on_year, ...)
        price_df: load_latest_price_all() 回傳值 (stock_id, close, volume)
        inst_df: load_latest_institutional_all() 回傳值 (stock_id, *_buy, *_sell)
        stock_names: 股票名稱 DataFrame (stock_id, name)，可選

    Returns:
        DataFrame [stock_id, name, close, volume, per, pbr, dividend_yield,
                   rev_yoy, inst_net_buy, is_target]
    """
    result = pd.DataFrame({"stock_id": peers})

    # 名稱
    if stock_names is not None and not stock_names.empty:
        result = result.merge(
            stock_names[["stock_id", "name"]], on="stock_id", how="left"
        )
    else:
        result["name"] = result["stock_id"]

    # 價格
    if not price_df.empty:
        cols = ["stock_id", "close"]
        if "volume" in price_df.columns:
            cols.append("volume")
        result = result.merge(price_df[cols], on="stock_id", how="left")

    # PER / PBR / 殖利率
    if not per_df.empty:
        per_cols = ["stock_id"]
        for c in ["per", "pbr", "dividend_yield"]:
            if c in per_df.columns:
                per_cols.append(c)
        if len(per_cols) > 1:
            result = result.merge(per_df[per_cols], on="stock_id", how="left")

    # 營收 YoY
    if not revenue_df.empty and "month_revenue_year_on_year" in revenue_df.columns:
        result = result.merge(
            revenue_df[["stock_id", "month_revenue_year_on_year"]].rename(
                columns={"month_revenue_year_on_year": "rev_yoy"}
            ),
            on="stock_id", how="left",
        )

    # 法人淨買超
    if not inst_df.empty:
        inst = inst_df.copy()
        buy_cols = [c for c in inst.columns if c.endswith("_buy")]
        sell_cols = [c for c in inst.columns if c.endswith("_sell")]
        if buy_cols and sell_cols:
            for c in buy_cols + sell_cols:
                inst[c] = pd.to_numeric(inst[c], errors="coerce").fillna(0)
            inst["inst_net_buy"] = (
                inst[buy_cols].sum(axis=1) - inst[sell_cols].sum(axis=1)
            )
            result = result.merge(
                inst[["stock_id", "inst_net_buy"]], on="stock_id", how="left"
            )

    # 標記目標股
    result["is_target"] = result["stock_id"] == stock_id

    # 轉換數值型
    for col in ["close", "volume", "per", "pbr", "dividend_yield", "rev_yoy", "inst_net_buy"]:
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce")

    return result


def calc_peer_percentile(
    stock_id: str,
    metrics_df: pd.DataFrame,
) -> dict:
    """計算目標股在同業中各指標的百分位排名（0~100）

    百分位越高 = 該指標越大。例如 PER 百分位高 = 比較貴。

    Returns:
        {"per_pct": 25.0, "pbr_pct": 30.0, "dividend_yield_pct": 80.0,
         "rev_yoy_pct": 75.0, "inst_net_buy_pct": 60.0,
         "peer_count": 15, "sector": "...", "sub_industry": "..."}
    """
    result = {}
    target = metrics_df[metrics_df["stock_id"] == stock_id]
    if target.empty:
        return result

    result["peer_count"] = len(metrics_df)
    target_row = target.iloc[0]

    metric_cols = ["per", "pbr", "dividend_yield", "rev_yoy", "inst_net_buy"]
    for col in metric_cols:
        if col not in metrics_df.columns:
            continue
        vals = pd.to_numeric(metrics_df[col], errors="coerce").dropna()
        if vals.empty:
            continue
        target_val = target_row.get(col)
        if pd.isna(target_val):
            continue
        target_val = float(target_val)
        # 百分位 = 有多少比例的值 <= 目標值
        pct = (vals <= target_val).mean() * 100
        result[f"{col}_pct"] = round(pct, 1)

    return result
