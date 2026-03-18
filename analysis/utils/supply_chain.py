"""
產業供應鏈連動分析 — 定義上下游關係，計算營收動能傳導與領先落後
"""

import numpy as np
import pandas as pd

# 上游 → 下游的順序
SUPPLY_CHAIN = {
    "半導體供應鏈": [
        "IC 設計",
        "晶圓代工",
        "IC 製造",
        "IC 封測",
        "導線架",
    ],
    "電子組裝供應鏈": [
        "印刷電路板",
        "被動元件",
        "連接器",
        "電源供應器",
        "主機板",
        "伺服器",
        "筆記型電腦",
        "電腦系統",
    ],
    "面板供應鏈": [
        "LED",
        "TFT-LCD",
        "光通訊",
    ],
    "通訊供應鏈": [
        "網路設備",
        "電信設備",
        "行動電話",
    ],
    "消費電子供應鏈": [
        "LED",
        "光通訊",
        "消費性電子",
        "行動電話",
        "資訊通路",
    ],
    "汽車供應鏈": [
        "汽車零件",
        "整車",
    ],
    "化學工業供應鏈": [
        "塑化原料",
        "電子化學",
        "特用化學",
    ],
    "生技醫療供應鏈": [
        "原料藥/學名藥",
        "新藥研發",
        "醫材/醫療器材",
        "醫美/保健",
    ],
    "鋼鐵供應鏈": [
        "鋼鐵",
        "不鏽鋼",
        "特殊鋼/合金",
    ],
    "食品供應鏈": [
        "飼料/油脂",
        "食品加工",
        "飲料/乳品",
    ],
    "航運供應鏈": [
        "貨櫃航運",
        "散裝航運",
        "航空",
    ],
    "建築供應鏈": [
        "營造",
        "建設/房地產",
    ],
    "紡織供應鏈": [
        "機能布/紡紗",
        "成衣/代工",
    ],
}


def get_chain_names() -> list[str]:
    """回傳所有供應鏈名稱"""
    return list(SUPPLY_CHAIN.keys())


def get_chain_stages(chain_name: str) -> list[str]:
    """回傳供應鏈各環節（上游→下游順序）"""
    return SUPPLY_CHAIN.get(chain_name, [])


def calc_chain_momentum(
    chain_name: str,
    revenue_df: pd.DataFrame,
    industry_map: pd.DataFrame,
    lookback_months: int = 3,
) -> pd.DataFrame:
    """計算供應鏈各環節的營收動能

    Parameters:
        chain_name: 供應鏈名稱
        revenue_df: 月營收資料 (stock_id, date, revenue, month_revenue_year_on_year)
        industry_map: (stock_id, sector, sub_industry)
        lookback_months: 營收回溯月數

    Returns:
        DataFrame [sub_industry, avg_yoy, median_yoy, stock_count, chain_order]
    """
    stages = SUPPLY_CHAIN.get(chain_name, [])
    if not stages or revenue_df.empty or industry_map.empty:
        return pd.DataFrame()

    if "sub_industry" not in industry_map.columns:
        return pd.DataFrame()

    # 篩選供應鏈內的股票
    chain_stocks = industry_map[industry_map["sub_industry"].isin(stages)]
    if chain_stocks.empty:
        return pd.DataFrame()

    df = revenue_df.merge(chain_stocks[["stock_id", "sub_industry"]], on="stock_id", how="inner")
    if df.empty:
        return pd.DataFrame()

    # 時間篩選
    df["date"] = pd.to_datetime(df["date"])
    latest = df["date"].max()
    cutoff = latest - pd.DateOffset(months=lookback_months)
    df = df[df["date"] >= cutoff]

    if df.empty or "month_revenue_year_on_year" not in df.columns:
        return pd.DataFrame()

    yoy_col = "month_revenue_year_on_year"
    df[yoy_col] = pd.to_numeric(df[yoy_col], errors="coerce")

    result = df.groupby("sub_industry").agg(
        avg_yoy=(yoy_col, "mean"),
        median_yoy=(yoy_col, "median"),
        stock_count=("stock_id", "nunique"),
    ).reset_index()

    # 加入供應鏈順序
    stage_order = {s: i for i, s in enumerate(stages)}
    result["chain_order"] = result["sub_industry"].map(stage_order)
    result = result.dropna(subset=["chain_order"])
    result["chain_order"] = result["chain_order"].astype(int)
    result = result.sort_values("chain_order")

    return result.reset_index(drop=True)


def calc_chain_lead_lag(
    chain_name: str,
    revenue_df: pd.DataFrame,
    industry_map: pd.DataFrame,
    periods: int = 12,
) -> pd.DataFrame:
    """計算供應鏈上下游的領先/落後關係（交叉相關分析）

    Parameters:
        chain_name: 供應鏈名稱
        revenue_df: 月營收資料
        industry_map: (stock_id, sector, sub_industry)
        periods: 分析期數（月）

    Returns:
        DataFrame 矩陣 (index=sub_industry, columns=sub_industry, values=lag months)
        正值 = 行領先列（例如 IC設計 row, IC封測 col = 2 → IC設計領先封測 2 個月）
    """
    stages = SUPPLY_CHAIN.get(chain_name, [])
    if not stages or revenue_df.empty or industry_map.empty:
        return pd.DataFrame()

    if "sub_industry" not in industry_map.columns:
        return pd.DataFrame()

    chain_stocks = industry_map[industry_map["sub_industry"].isin(stages)]
    if chain_stocks.empty:
        return pd.DataFrame()

    df = revenue_df.merge(chain_stocks[["stock_id", "sub_industry"]], on="stock_id", how="inner")
    if df.empty or "month_revenue_year_on_year" not in df.columns:
        return pd.DataFrame()

    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.to_period("M")
    df["month_revenue_year_on_year"] = pd.to_numeric(
        df["month_revenue_year_on_year"], errors="coerce"
    )

    # 建立各環節月度 YoY 時間序列
    monthly = df.groupby(["sub_industry", "month"])["month_revenue_year_on_year"].mean()
    monthly = monthly.unstack(level=0)

    # 只取最近 periods 個月
    if len(monthly) > periods:
        monthly = monthly.iloc[-periods:]

    # 取存在資料的環節
    available = [s for s in stages if s in monthly.columns]
    if len(available) < 2:
        return pd.DataFrame()

    monthly = monthly[available].dropna(how="all")
    if len(monthly) < 4:
        return pd.DataFrame()

    # 計算兩兩交叉相關，找最大相關的 lag
    max_lag = min(6, len(monthly) // 2)
    result = pd.DataFrame(0.0, index=available, columns=available)

    for i, a in enumerate(available):
        for j, b in enumerate(available):
            if i == j:
                continue
            sa = monthly[a].dropna()
            sb = monthly[b].dropna()
            # 對齊時間
            common = sa.index.intersection(sb.index)
            if len(common) < 4:
                continue
            sa = sa.loc[common].values.astype(float)
            sb = sb.loc[common].values.astype(float)

            # 標準化
            sa_std = np.std(sa)
            sb_std = np.std(sb)
            if sa_std == 0 or sb_std == 0:
                continue
            sa_norm = (sa - np.mean(sa)) / sa_std
            sb_norm = (sb - np.mean(sb)) / sb_std

            best_lag = 0
            best_corr = 0
            for lag in range(-max_lag, max_lag + 1):
                if lag > 0:
                    corr = np.mean(sa_norm[lag:] * sb_norm[:-lag]) if lag < len(sa_norm) else 0
                elif lag < 0:
                    corr = np.mean(sa_norm[:lag] * sb_norm[-lag:]) if -lag < len(sb_norm) else 0
                else:
                    corr = np.mean(sa_norm * sb_norm)
                if abs(corr) > abs(best_corr):
                    best_corr = corr
                    best_lag = lag

            result.loc[a, b] = best_lag

    return result
