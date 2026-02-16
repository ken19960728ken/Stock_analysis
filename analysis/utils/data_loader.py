"""
統一資料查詢層 — 複用 core/db.py 的 get_engine()，加 Streamlit cache
"""

import os

import pandas as pd
import streamlit as st

from core.db import get_engine

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
        return pd.read_sql(sql, get_engine())
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
        df = pd.read_sql(sql, get_engine(), params=params)
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
        df = pd.read_sql(sql, get_engine(), params={"sid": stock_id})
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
        df = pd.read_sql(sql, get_engine(), params={"sid": stock_id})
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
        df = pd.read_sql(sql, get_engine(), params={"sid": stock_id})
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
        df = pd.read_sql(sql, get_engine(), params={"sid": stock_id})
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
        df = pd.read_sql(sql, get_engine(), params={"sid": stock_id})
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
        df = pd.read_sql(sql, get_engine(), params={"sid": stock_id})
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
        df = pd.read_sql(sql, get_engine(), params={"sid": stock_id})
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
        df = pd.read_sql(sql, get_engine(), params={"sid": stock_id})
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_month_revenue(stock_id: str) -> pd.DataFrame:
    """月營收"""
    sql = "SELECT * FROM month_revenue WHERE stock_id = %(sid)s ORDER BY date"
    try:
        df = pd.read_sql(sql, get_engine(), params={"sid": stock_id})
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_stock_per(stock_id: str) -> pd.DataFrame:
    """本益比/股價淨值比/殖利率"""
    sql = "SELECT * FROM stock_per WHERE stock_id = %(sid)s ORDER BY date"
    try:
        df = pd.read_sql(sql, get_engine(), params={"sid": stock_id})
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
        df = pd.read_sql(sql, get_engine(), params={"sid": stock_id})
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_latest_per_all() -> pd.DataFrame:
    """取得所有股票最新的 PER/PBR/殖利率"""
    sql = """
    SELECT DISTINCT ON (stock_id) stock_id, date, per, pbr, dividend_yield
    FROM stock_per
    ORDER BY stock_id, date DESC
    """
    try:
        return pd.read_sql(sql, get_engine())
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_latest_revenue_all() -> pd.DataFrame:
    """取得所有股票最新月營收"""
    sql = """
    SELECT DISTINCT ON (stock_id) *
    FROM month_revenue
    ORDER BY stock_id, date DESC
    """
    try:
        return pd.read_sql(sql, get_engine())
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_latest_price_all() -> pd.DataFrame:
    """取得所有股票最新收盤價"""
    sql = """
    SELECT DISTINCT ON (stock_id) stock_id, date, close, volume
    FROM daily_price
    ORDER BY stock_id, date DESC
    """
    try:
        return pd.read_sql(sql, get_engine())
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_latest_institutional_all() -> pd.DataFrame:
    """取得所有股票最新法人買賣超"""
    sql = """
    SELECT DISTINCT ON (stock_id) *
    FROM chip_institutional
    ORDER BY stock_id, date DESC
    """
    try:
        return pd.read_sql(sql, get_engine())
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_market_summary() -> dict:
    """市場總覽統計"""
    engine = get_engine()
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
        df = pd.read_sql(sql, engine)
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
        df = pd.read_sql(text(sql), get_engine(), params=params)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception:
        return pd.DataFrame()
