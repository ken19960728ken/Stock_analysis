"""
統一資料查詢層 — 複用 core/db.py 的 get_engine()，加 Streamlit cache
"""

import os

import pandas as pd

try:
    import streamlit as st
except ImportError:
    # Pipeline 環境（無 streamlit）：用 no-op decorator 替代 @st.cache_data
    import types
    st = types.SimpleNamespace(
        cache_data=lambda **kwargs: (lambda fn: fn),
    )

from core.db import get_engine, safe_read_sql


# ---------------------------------------------------------------------------
# 月營收 YoY 計算（FinMind API 不提供 YoY，須自行計算）
# ---------------------------------------------------------------------------

def _compute_revenue_yoy(df: pd.DataFrame) -> pd.DataFrame:
    """從 revenue + revenue_year + revenue_month 計算月營收年增率。

    新增 month_revenue_year_on_year 欄位（百分比，如 15.3 表示 +15.3%）。
    需要 revenue, revenue_year, revenue_month 三個欄位。
    """
    if df.empty:
        return df
    required = {"revenue", "revenue_year", "revenue_month"}
    if not required.issubset(df.columns):
        return df

    result = df.copy()

    # 建立 (stock_id, year, month) → revenue 查找表
    has_sid = "stock_id" in result.columns
    if has_sid:
        lookup = result.dropna(subset=["revenue", "revenue_year", "revenue_month"])
        lookup_map = lookup.set_index(
            ["stock_id", "revenue_year", "revenue_month"]
        )["revenue"].to_dict()

        prev_year = result["revenue_year"] - 1
        prev_keys = list(zip(result["stock_id"], prev_year, result["revenue_month"]))
    else:
        lookup = result.dropna(subset=["revenue", "revenue_year", "revenue_month"])
        lookup_map = lookup.set_index(
            ["revenue_year", "revenue_month"]
        )["revenue"].to_dict()

        prev_year = result["revenue_year"] - 1
        prev_keys = list(zip(prev_year, result["revenue_month"]))

    prev_rev = pd.Series(
        [lookup_map.get(k) for k in prev_keys],
        index=result.index, dtype=float,
    )
    mask = prev_rev.notna() & (prev_rev > 0) & result["revenue"].notna()
    result["month_revenue_year_on_year"] = pd.NA
    result.loc[mask, "month_revenue_year_on_year"] = (
        (result.loc[mask, "revenue"].astype(float) / prev_rev.loc[mask] - 1) * 100
    ).round(2)

    return result


# ---------------------------------------------------------------------------
# FRED 經濟指標配置
# ---------------------------------------------------------------------------

FRED_INDICATORS = {
    # 美國總經
    "real_gdp":      {"series": "GDPC1",            "name": "美國實質 GDP",             "unit": "Billions USD", "freq": "quarterly"},
    "cpi":           {"series": "CPIAUCSL",          "name": "美國消費者物價指數",        "unit": "Index",        "freq": "monthly"},
    "unemployment":  {"series": "UNRATE",            "name": "美國失業率",               "unit": "%",            "freq": "monthly"},
    "fed_funds":     {"series": "FEDFUNDS",          "name": "聯邦基金利率",             "unit": "%",            "freq": "monthly"},
    # 美國市場
    "sp500":         {"series": "SP500",             "name": "S&P 500 指數",            "unit": "Index",        "freq": "daily"},
    "nasdaq":        {"series": "NASDAQ100",         "name": "NASDAQ 100 指數",         "unit": "Index",        "freq": "daily"},
    "treasury_10y":  {"series": "DGS10",             "name": "美國 10 年期公債殖利率",    "unit": "%",            "freq": "daily"},
    "treasury_2y":   {"series": "DGS2",              "name": "美國 2 年期公債殖利率",     "unit": "%",            "freq": "daily"},
    # 商品與台灣
    "oil_wti":       {"series": "DCOILWTICO",        "name": "WTI 原油價格",             "unit": "USD/barrel",   "freq": "daily"},
    "gold":          {"series": "GOLDAMGBD228NLBM",  "name": "黃金價格(倫敦)",           "unit": "USD/oz",       "freq": "daily"},
    "twn_cpi":       {"series": "TWNPCPIPCPPPT",     "name": "台灣消費者物價指數",        "unit": "% YoY",        "freq": "annual"},
    "twn_export":    {"series": "VALEXPTWM052N",     "name": "台灣出口值",               "unit": "Millions USD", "freq": "monthly"},
}

FRED_CATEGORIES = {
    "美國總經": ["real_gdp", "cpi", "unemployment", "fed_funds"],
    "美國市場": ["sp500", "nasdaq", "treasury_10y", "treasury_2y"],
    "商品與台灣": ["oil_wti", "gold", "twn_cpi", "twn_export"],
}


def _get_fred_client():
    """懶載入 FRED client，缺 key 回傳 None"""
    try:
        from fredapi import Fred
    except ImportError:
        return None
    api_key = os.environ.get("FRED_API_KEY", "")
    if not api_key:
        from dotenv import load_dotenv
        load_dotenv()
        api_key = os.environ.get("FRED_API_KEY", "")
    if not api_key:
        return None
    return Fred(api_key=api_key)


def is_fred_available() -> bool:
    """檢查 FRED API key 是否可用"""
    return _get_fred_client() is not None


@st.cache_data(ttl=3600)
def load_fred_series(series_key: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """取得單一 FRED 指標，回傳 DataFrame [date, value]"""
    if series_key not in FRED_INDICATORS:
        return pd.DataFrame(columns=["date", "value"])
    client = _get_fred_client()
    if client is None:
        return pd.DataFrame(columns=["date", "value"])
    try:
        series_id = FRED_INDICATORS[series_key]["series"]
        data = client.get_series(series_id, observation_start=start_date, observation_end=end_date)
        df = data.dropna().reset_index()
        df.columns = ["date", "value"]
        df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame(columns=["date", "value"])


@st.cache_data(ttl=300)
def get_stock_list() -> pd.DataFrame:
    """取得所有股票清單 (stock_id, name, type, market)"""
    sql = """
    SELECT "商品代號" AS stock_id,
           "商品名稱" AS name,
           "商品類型" AS type,
           "市場別"   AS market
    FROM twstock_code
    WHERE "CFICode" = 'ESVUFR' OR "商品類型" = 'ETF'
    ORDER BY "商品代號"
    """
    try:
        return safe_read_sql(sql)
    except Exception:
        return pd.DataFrame(columns=["stock_id", "name", "type", "market"])


def get_stock_options() -> dict:
    """返回 {display_label: stock_id} 映射，用於 selectbox"""
    df = get_stock_list()
    return {f"{row['stock_id']} {row['name']}": row["stock_id"] for _, row in df.iterrows()}


@st.cache_data(ttl=300)
def load_daily_price(stock_id: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """載入日K資料"""
    sql = "SELECT * FROM daily_price WHERE stock_id = %(sid)s"
    params = {"sid": stock_id}
    if start_date:
        sql += " AND date >= %(start)s"
        params["start"] = start_date
    if end_date:
        sql += " AND date <= %(end)s"
        params["end"] = end_date
    sql += " ORDER BY date"
    try:
        df = safe_read_sql(sql, params=params)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_weekly_price(stock_id: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """載入週K資料"""
    sql = "SELECT * FROM weekly_price WHERE stock_id = %(sid)s"
    params = {"sid": stock_id}
    if start_date:
        sql += " AND date >= %(start)s"
        params["start"] = start_date
    if end_date:
        sql += " AND date <= %(end)s"
        params["end"] = end_date
    sql += " ORDER BY date"
    try:
        df = safe_read_sql(sql, params=params)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_monthly_price(stock_id: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """載入月K資料"""
    sql = "SELECT * FROM monthly_price WHERE stock_id = %(sid)s"
    params = {"sid": stock_id}
    if start_date:
        sql += " AND date >= %(start)s"
        params["start"] = start_date
    if end_date:
        sql += " AND date <= %(end)s"
        params["end"] = end_date
    sql += " ORDER BY date"
    try:
        df = safe_read_sql(sql, params=params)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_chip_institutional(stock_id: str) -> pd.DataFrame:
    """三大法人買賣超"""
    sql = "SELECT * FROM chip_institutional WHERE stock_id = %(sid)s ORDER BY date"
    try:
        df = safe_read_sql(sql, params={"sid": stock_id})
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_chip_margin(stock_id: str) -> pd.DataFrame:
    """融資融券"""
    sql = "SELECT * FROM chip_margin WHERE stock_id = %(sid)s ORDER BY date"
    try:
        df = safe_read_sql(sql, params={"sid": stock_id})
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_chip_shareholding(stock_id: str) -> pd.DataFrame:
    """股權分散表"""
    sql = "SELECT * FROM chip_shareholding WHERE stock_id = %(sid)s ORDER BY date"
    try:
        df = safe_read_sql(sql, params={"sid": stock_id})
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_chip_holding_pct(stock_id: str) -> pd.DataFrame:
    """持股比例"""
    sql = "SELECT * FROM chip_holding_pct WHERE stock_id = %(sid)s ORDER BY date"
    try:
        df = safe_read_sql(sql, params={"sid": stock_id})
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_chip_securities_lending(stock_id: str) -> pd.DataFrame:
    """借券資料"""
    sql = "SELECT * FROM chip_securities_lending WHERE stock_id = %(sid)s ORDER BY date"
    try:
        df = safe_read_sql(sql, params={"sid": stock_id})
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_chip_short_sale(stock_id: str) -> pd.DataFrame:
    """借券賣出餘額"""
    sql = "SELECT * FROM chip_short_sale WHERE stock_id = %(sid)s ORDER BY date"
    try:
        df = safe_read_sql(sql, params={"sid": stock_id})
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_financial_reports(stock_id: str) -> pd.DataFrame:
    """財務報表"""
    sql = "SELECT * FROM financial_reports WHERE stock_id = %(sid)s ORDER BY date"
    try:
        df = safe_read_sql(sql, params={"sid": stock_id})
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_dividend_history(stock_id: str) -> pd.DataFrame:
    """股利歷史"""
    sql = "SELECT * FROM dividend_history WHERE stock_id = %(sid)s ORDER BY date"
    try:
        df = safe_read_sql(sql, params={"sid": stock_id})
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_month_revenue(stock_id: str) -> pd.DataFrame:
    """月營收（含自行計算的 month_revenue_year_on_year）"""
    sql = "SELECT * FROM month_revenue WHERE stock_id = %(sid)s ORDER BY date"
    try:
        df = safe_read_sql(sql, params={"sid": stock_id})
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        df = _compute_revenue_yoy(df)
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_stock_per(stock_id: str) -> pd.DataFrame:
    """本益比/股價淨值比/殖利率"""
    sql = "SELECT * FROM stock_per WHERE stock_id = %(sid)s ORDER BY date"
    try:
        df = safe_read_sql(sql, params={"sid": stock_id})
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_market_value(stock_id: str) -> pd.DataFrame:
    """市值"""
    sql = "SELECT * FROM market_value WHERE stock_id = %(sid)s ORDER BY date"
    try:
        df = safe_read_sql(sql, params={"sid": stock_id})
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_financial_ratios(stock_id: str) -> pd.DataFrame:
    """從 financial_reports 長格式 pivot 出寬格式，計算三率"""
    sql = "SELECT * FROM financial_reports WHERE stock_id = %(sid)s ORDER BY date"
    try:
        df = safe_read_sql(sql, params={"sid": stock_id})
        if df.empty or "type" not in df.columns:
            return pd.DataFrame()

        # pivot 長格式 → 寬格式
        pivoted = df.pivot_table(index=["date", "stock_id"], columns="type",
                                 values="value", aggfunc="first").reset_index()
        pivoted.columns.name = None

        # 計算三率
        if "Revenue" in pivoted.columns and "GrossProfit" in pivoted.columns:
            rev = pd.to_numeric(pivoted["Revenue"], errors="coerce")
            pivoted["gross_margin"] = pd.to_numeric(pivoted["GrossProfit"], errors="coerce") / rev.replace(0, float("nan")) * 100
        if "Revenue" in pivoted.columns and "OperatingIncome" in pivoted.columns:
            rev = pd.to_numeric(pivoted["Revenue"], errors="coerce")
            pivoted["operating_margin"] = pd.to_numeric(pivoted["OperatingIncome"], errors="coerce") / rev.replace(0, float("nan")) * 100
        if "Revenue" in pivoted.columns and "NetIncome" in pivoted.columns:
            rev = pd.to_numeric(pivoted["Revenue"], errors="coerce")
            pivoted["net_margin"] = pd.to_numeric(pivoted["NetIncome"], errors="coerce") / rev.replace(0, float("nan")) * 100

        return pivoted
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_latest_margin_all() -> pd.DataFrame:
    """DISTINCT ON (stock_id) 取最新融資融券"""
    sql = """
    SELECT DISTINCT ON (stock_id) *
    FROM chip_margin
    WHERE date >= CURRENT_DATE - INTERVAL '90 days'
    ORDER BY stock_id, date DESC
    """
    try:
        return safe_read_sql(sql)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_latest_shareholding_summary_all() -> pd.DataFrame:
    """取最新各股持股分散摘要（來自 chip_holding_pct 表）

    chip_holding_pct 欄位: date, stock_id, HoldingSharesLevel, people, percent, unit
    每支股票每個日期有多筆（不同持股級距），聚合為 total_people 和 total_percent。
    """
    sql = """
    SELECT stock_id, MAX(date) as date,
           SUM(percent) as total_holding_pct,
           SUM(people) as total_shareholder_count
    FROM (
        SELECT DISTINCT ON (stock_id, "HoldingSharesLevel") *
        FROM chip_holding_pct
        ORDER BY stock_id, "HoldingSharesLevel", date DESC
    ) latest
    GROUP BY stock_id
    """
    try:
        return safe_read_sql(sql)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def compute_revenue_growth_all() -> pd.DataFrame:
    """月營收年增率（自行計算 YoY，FinMind API 不提供此欄位）"""
    sql = """
    SELECT stock_id, date, revenue, revenue_month, revenue_year
    FROM month_revenue
    WHERE date >= CURRENT_DATE - INTERVAL '450 days'
    ORDER BY stock_id, date
    """
    try:
        df = safe_read_sql(sql)
        if df.empty:
            return pd.DataFrame()
        df = _compute_revenue_yoy(df)
        # 取每支股票最新一筆
        latest = df.sort_values("date").drop_duplicates(subset=["stock_id"], keep="last")
        result = latest[["stock_id", "revenue"]].copy()
        if "month_revenue_year_on_year" in latest.columns:
            result["revenue_yoy"] = latest["month_revenue_year_on_year"].values
        else:
            result["revenue_yoy"] = pd.NA
        return result.reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def compute_institutional_consecutive_days_all() -> pd.DataFrame:
    """法人連續買超天數"""
    sql = """
    SELECT stock_id, date,
           (foreign_investors_buy - foreign_investors_sell +
            investment_trust_buy - investment_trust_sell +
            dealer_buy - dealer_sell) as net_buy
    FROM chip_institutional
    WHERE date >= CURRENT_DATE - INTERVAL '30 days'
    ORDER BY stock_id, date DESC
    """
    try:
        df = safe_read_sql(sql)
        if df.empty:
            return pd.DataFrame()

        results = []
        for sid, group in df.groupby("stock_id"):
            group = group.sort_values("date", ascending=False)
            consecutive = 0
            for _, row in group.iterrows():
                if pd.notna(row["net_buy"]) and row["net_buy"] > 0:
                    consecutive += 1
                else:
                    break
            results.append({"stock_id": sid, "法人連買天數": consecutive})
        return pd.DataFrame(results)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def compute_shareholder_change_all() -> pd.DataFrame:
    """股東人數變化（最新 vs 4 週前），來自 chip_holding_pct 表

    chip_holding_pct 欄位: date, stock_id, HoldingSharesLevel, people, percent, unit
    """
    sql_latest = """
    SELECT DISTINCT ON (stock_id) stock_id,
           SUM(people) OVER (PARTITION BY stock_id, date) as total_count,
           date
    FROM chip_holding_pct
    ORDER BY stock_id, date DESC
    """
    sql_4w_ago = """
    SELECT DISTINCT ON (stock_id) stock_id,
           SUM(people) OVER (PARTITION BY stock_id, date) as total_count,
           date
    FROM chip_holding_pct
    WHERE date <= CURRENT_DATE - INTERVAL '28 days'
    ORDER BY stock_id, date DESC
    """
    try:
        latest = safe_read_sql(sql_latest)
        older = safe_read_sql(sql_4w_ago)
        if latest.empty or older.empty:
            return pd.DataFrame()

        merged = latest[["stock_id", "total_count"]].merge(
            older[["stock_id", "total_count"]],
            on="stock_id", suffixes=("_now", "_old"),
        )
        merged["股東人數變化%"] = (
            (merged["total_count_now"] - merged["total_count_old"])
            / merged["total_count_old"].replace(0, float("nan")) * 100
        )
        return merged[["stock_id", "股東人數變化%"]]
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_latest_per_all() -> pd.DataFrame:
    """取得所有股票最新的 PER/PBR/殖利率"""
    sql = """
    SELECT DISTINCT ON (stock_id) stock_id, date, per, pbr, dividend_yield
    FROM stock_per
    WHERE date >= CURRENT_DATE - INTERVAL '90 days'
    ORDER BY stock_id, date DESC
    """
    try:
        return safe_read_sql(sql)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_latest_revenue_all() -> pd.DataFrame:
    """取得所有股票最新月營收（含自行計算的 YoY）"""
    sql = """
    SELECT stock_id, date, country, revenue, revenue_month, revenue_year
    FROM month_revenue
    WHERE date >= CURRENT_DATE - INTERVAL '450 days'
    ORDER BY stock_id, date
    """
    try:
        df = safe_read_sql(sql)
        if df.empty:
            return pd.DataFrame()
        df = _compute_revenue_yoy(df)
        # 取每支股票最新一筆
        latest = df.sort_values("date").drop_duplicates(subset=["stock_id"], keep="last")
        return latest.reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_latest_price_all() -> pd.DataFrame:
    """取得所有股票最新收盤價"""
    sql = """
    SELECT DISTINCT ON (stock_id) stock_id, date, close, volume
    FROM daily_price
    WHERE date >= CURRENT_DATE - INTERVAL '90 days'
    ORDER BY stock_id, date DESC
    """
    try:
        return safe_read_sql(sql)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_latest_institutional_all() -> pd.DataFrame:
    """取得所有股票最新法人買賣超"""
    sql = """
    SELECT DISTINCT ON (stock_id) *
    FROM chip_institutional
    WHERE date >= CURRENT_DATE - INTERVAL '90 days'
    ORDER BY stock_id, date DESC
    """
    try:
        return safe_read_sql(sql)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_market_summary() -> dict:
    """市場總覽統計"""
    result = {}
    try:
        # 上漲/下跌家數
        sql = """
        WITH latest AS (
            SELECT DISTINCT ON (stock_id) stock_id, close, open
            FROM daily_price
            ORDER BY stock_id, date DESC
        )
        SELECT
            COUNT(CASE WHEN close > open THEN 1 END) AS up_count,
            COUNT(CASE WHEN close < open THEN 1 END) AS down_count,
            COUNT(CASE WHEN close = open THEN 1 END) AS flat_count,
            COUNT(*) AS total
        FROM latest
        """
        df = safe_read_sql(sql)
        if not df.empty:
            result["up_count"] = int(df.iloc[0]["up_count"])
            result["down_count"] = int(df.iloc[0]["down_count"])
            result["flat_count"] = int(df.iloc[0]["flat_count"])
            result["total"] = int(df.iloc[0]["total"])
    except Exception:
        pass
    return result


@st.cache_data(ttl=600)
def load_daily_price_multi(stock_ids: list, start_date: str = None) -> pd.DataFrame:
    """批次載入多支股票的日K"""
    if not stock_ids:
        return pd.DataFrame()
    from sqlalchemy import text
    # 參數化查詢防止 SQL 注入
    placeholders = ", ".join([f":sid_{i}" for i in range(len(stock_ids))])
    sql = f"SELECT * FROM daily_price WHERE stock_id IN ({placeholders})"
    params = {f"sid_{i}": sid for i, sid in enumerate(stock_ids)}
    if start_date:
        sql += " AND date >= :start_date"
        params["start_date"] = start_date
    sql += " ORDER BY stock_id, date"
    try:
        df = safe_read_sql(text(sql), params=params)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_stock_per_multi(stock_ids: list, start_date: str = None) -> pd.DataFrame:
    """批次載入多支股票的 PER/PBR/殖利率時間序列"""
    if not stock_ids:
        return pd.DataFrame()
    from sqlalchemy import text
    placeholders = ", ".join([f":sid_{i}" for i in range(len(stock_ids))])
    sql = f"SELECT stock_id, date, per, pbr, dividend_yield FROM stock_per WHERE stock_id IN ({placeholders})"
    params = {f"sid_{i}": sid for i, sid in enumerate(stock_ids)}
    if start_date:
        sql += " AND date >= :start_date"
        params["start_date"] = start_date
    sql += " ORDER BY stock_id, date"
    try:
        df = safe_read_sql(text(sql), params=params)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_chip_institutional_multi(stock_ids: list, start_date: str = None) -> pd.DataFrame:
    """批次載入多支股票的三大法人買賣超"""
    if not stock_ids:
        return pd.DataFrame()
    from sqlalchemy import text
    placeholders = ", ".join([f":sid_{i}" for i in range(len(stock_ids))])
    sql = f"SELECT * FROM chip_institutional WHERE stock_id IN ({placeholders})"
    params = {f"sid_{i}": sid for i, sid in enumerate(stock_ids)}
    if start_date:
        sql += " AND date >= :start_date"
        params["start_date"] = start_date
    sql += " ORDER BY stock_id, date"
    try:
        df = safe_read_sql(text(sql), params=params)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_top_volume_stocks(n: int = 50, lookback_days: int = 30) -> list:
    """取得近 N 天平均成交量 Top N 的 stock_id 清單"""
    sql = """
    SELECT stock_id, AVG(volume) as avg_volume
    FROM daily_price
    WHERE date >= CURRENT_DATE - INTERVAL ':lookback days'
    GROUP BY stock_id
    ORDER BY avg_volume DESC
    LIMIT :n
    """
    from sqlalchemy import text
    try:
        df = safe_read_sql(
            text(
                "SELECT stock_id, AVG(volume) as avg_volume "
                "FROM daily_price "
                "WHERE date >= CURRENT_DATE - :lookback * INTERVAL '1 day' "
                "GROUP BY stock_id "
                "ORDER BY avg_volume DESC "
                "LIMIT :n"
            ),
            params={"lookback": lookback_days, "n": n},
        )
        return df["stock_id"].tolist() if not df.empty else []
    except Exception:
        return []


@st.cache_data(ttl=3600)
def load_industry_mapping() -> pd.DataFrame:
    """stock_id -> industry_category（含 sector, sub_industry）

    優先讀 industry_classification 新表，若空 fallback 到舊 industry_mapping 表。
    回傳欄位：stock_id, industry_category, sector, sub_industry
    """
    # 優先讀新表
    sql_new = ("SELECT stock_id, sector, sub_industry, "
               "sector AS industry_category "
               "FROM industry_classification")
    try:
        df = safe_read_sql(sql_new)
        if not df.empty:
            return df
    except Exception:
        pass

    # Fallback 舊表
    sql_old = "SELECT stock_id, industry_category FROM industry_mapping"
    try:
        df = safe_read_sql(sql_old)
        if not df.empty:
            df["sector"] = df["industry_category"]
            df["sub_industry"] = None
            return df
    except Exception:
        pass

    return pd.DataFrame(columns=["stock_id", "industry_category", "sector", "sub_industry"])


@st.cache_data(ttl=600)
def load_month_revenue_all(start_date: str = None) -> pd.DataFrame:
    """全市場月營收（含自行計算的 month_revenue_year_on_year）"""
    # 多抓 450 天以便計算 YoY（需要去年同期數據）
    if start_date:
        from datetime import datetime, timedelta
        yoy_start = (datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=400)).strftime("%Y-%m-%d")
        sql = "SELECT * FROM month_revenue WHERE date >= %(start)s ORDER BY stock_id, date"
        params = {"start": yoy_start}
    else:
        sql = "SELECT * FROM month_revenue ORDER BY stock_id, date"
        params = {}
    try:
        df = safe_read_sql(sql, params=params)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        df = _compute_revenue_yoy(df)
        # 若有 start_date，過濾回原始範圍
        if start_date:
            df = df[df["date"] >= pd.Timestamp(start_date)].reset_index(drop=True)
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_chip_institutional_all(start_date: str = None) -> pd.DataFrame:
    """全市場法人買賣超"""
    sql = "SELECT * FROM chip_institutional"
    params = {}
    if start_date:
        sql += " WHERE date >= %(start)s"
        params["start"] = start_date
    sql += " ORDER BY stock_id, date"
    try:
        df = safe_read_sql(sql, params=params)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_dividend_events_all(start_date: str = None) -> pd.DataFrame:
    """全市場除息事件"""
    sql = "SELECT * FROM dividend_history"
    params = {}
    if start_date:
        sql += " WHERE date >= %(start)s"
        params["start"] = start_date
    sql += " ORDER BY stock_id, date"
    try:
        df = safe_read_sql(sql, params=params)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_earnings_dates_all(start_date: str = None) -> pd.DataFrame:
    """全市場財報公布日 (從 financial_reports 取 type='EarningsPerShare' 的日期)"""
    sql = """
    SELECT stock_id, date, value as eps_value
    FROM financial_reports
    WHERE type = 'EarningsPerShare'
    """
    params = {}
    if start_date:
        sql += " AND date >= %(start)s"
        params["start"] = start_date
    sql += " ORDER BY stock_id, date"
    try:
        df = safe_read_sql(sql, params=params)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_stock_per_all(start_date: str | None = None) -> pd.DataFrame:
    """全市場 PER/PBR/殖利率"""
    sql = "SELECT stock_id, date, per, pbr, dividend_yield FROM stock_per"
    params = {}
    if start_date:
        sql += " WHERE date >= %(start)s"
        params["start"] = start_date
    sql += " ORDER BY stock_id, date"
    try:
        df = safe_read_sql(sql, params=params)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_daily_price_all(start_date: str = None) -> pd.DataFrame:
    """全市場日K（用於事件研究等全市場分析）"""
    sql = "SELECT stock_id, date, open, high, low, close, volume FROM daily_price"
    params = {}
    if start_date:
        sql += " WHERE date >= %(start)s"
        params["start"] = start_date
    sql += " ORDER BY stock_id, date"
    try:
        df = safe_read_sql(sql, params=params)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()
