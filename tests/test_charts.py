"""
Plotly 圖表工廠測試 — analysis/utils/charts.py
驗證所有圖表函數正確回傳 go.Figure，含正常資料與空資料邊界
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest

from analysis.utils.charts import (
    create_candlestick_chart,
    create_chip_chart,
    create_correlation_heatmap,
    create_economic_indicator_chart,
    create_equity_curve,
    create_fundamental_chart,
    create_margin_chart,
    create_monthly_heatmap,
    create_treemap,
    create_yield_spread_chart,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def ohlcv_df():
    """50 天 OHLCV"""
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=50, freq="B")
    close = 500 + np.cumsum(np.random.randn(50) * 3)
    return pd.DataFrame({
        "date": dates,
        "open": close - 1,
        "high": close + 3,
        "low": close - 3,
        "close": close,
        "volume": np.random.randint(10_000_000, 50_000_000, 50),
    })


@pytest.fixture
def ohlcv_with_indicators(ohlcv_df):
    """含技術指標的 OHLCV"""
    from analysis.utils.indicators import compute_all_indicators
    return compute_all_indicators(ohlcv_df.copy())


@pytest.fixture
def institutional_df():
    dates = pd.date_range("2023-01-01", periods=30, freq="B")
    return pd.DataFrame({
        "date": dates,
        "stock_id": ["2330"] * 30,
        "foreign_investors_buy": np.random.randint(-5000, 5000, 30),
    })


@pytest.fixture
def margin_df():
    dates = pd.date_range("2023-01-01", periods=30, freq="B")
    return pd.DataFrame({
        "date": dates,
        "stock_id": ["2330"] * 30,
        "margin_purchase_balance": np.random.randint(8000, 12000, 30),
        "short_sale_balance": np.random.randint(3000, 6000, 30),
    })


@pytest.fixture
def equity_series():
    dates = pd.date_range("2023-01-01", periods=100, freq="B")
    np.random.seed(42)
    values = 100 + np.cumsum(np.random.randn(100) * 1.5)
    return pd.Series(values, index=dates)


@pytest.fixture
def monthly_returns():
    idx = pd.date_range("2021-01-31", periods=24, freq="ME")
    np.random.seed(42)
    return pd.Series(np.random.randn(24) * 0.05, index=idx)


# ============================================================================
# K 線圖
# ============================================================================

class TestCreateCandlestickChart:
    def test_basic(self, ohlcv_df):
        fig = create_candlestick_chart(ohlcv_df)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) > 0

    def test_empty_data(self):
        fig = create_candlestick_chart(pd.DataFrame())
        assert isinstance(fig, go.Figure)

    def test_with_volume(self, ohlcv_df):
        fig = create_candlestick_chart(ohlcv_df, show_volume=True)
        assert isinstance(fig, go.Figure)

    def test_with_ma(self, ohlcv_with_indicators):
        fig = create_candlestick_chart(
            ohlcv_with_indicators,
            ma_periods=[5, 20],
        )
        assert isinstance(fig, go.Figure)

    def test_with_bollinger(self, ohlcv_with_indicators):
        fig = create_candlestick_chart(
            ohlcv_with_indicators,
            show_bollinger=True,
        )
        assert isinstance(fig, go.Figure)

    def test_with_sar(self, ohlcv_with_indicators):
        fig = create_candlestick_chart(
            ohlcv_with_indicators,
            show_sar=True,
        )
        assert isinstance(fig, go.Figure)

    def test_heikin_ashi(self, ohlcv_with_indicators):
        fig = create_candlestick_chart(
            ohlcv_with_indicators,
            heikin_ashi=True,
        )
        assert isinstance(fig, go.Figure)

    def test_with_indicators(self, ohlcv_with_indicators):
        fig = create_candlestick_chart(
            ohlcv_with_indicators,
            indicators=["MACD", "RSI", "KD"],
        )
        assert isinstance(fig, go.Figure)

    def test_williams_and_ao(self, ohlcv_with_indicators):
        fig = create_candlestick_chart(
            ohlcv_with_indicators,
            indicators=["威廉", "AO"],
        )
        assert isinstance(fig, go.Figure)

    def test_with_trades(self, ohlcv_df):
        trades = pd.DataFrame({
            "date": [ohlcv_df["date"].iloc[10], ohlcv_df["date"].iloc[30]],
            "action": ["buy", "sell"],
            "price": [ohlcv_df["close"].iloc[10], ohlcv_df["close"].iloc[30]],
        })
        fig = create_candlestick_chart(ohlcv_df, trades=trades)
        assert isinstance(fig, go.Figure)

    def test_title(self, ohlcv_df):
        fig = create_candlestick_chart(ohlcv_df, title="2330 台積電")
        assert isinstance(fig, go.Figure)


# ============================================================================
# 籌碼圖
# ============================================================================

class TestCreateChipChart:
    def test_basic(self, ohlcv_df, institutional_df):
        fig = create_chip_chart(ohlcv_df, institutional_df)
        assert isinstance(fig, go.Figure)

    def test_empty_institutional(self, ohlcv_df):
        fig = create_chip_chart(ohlcv_df, pd.DataFrame())
        assert isinstance(fig, go.Figure)

    def test_empty_price(self, institutional_df):
        fig = create_chip_chart(pd.DataFrame(), institutional_df)
        assert isinstance(fig, go.Figure)


# ============================================================================
# 融資融券圖
# ============================================================================

class TestCreateMarginChart:
    def test_basic(self, margin_df):
        fig = create_margin_chart(margin_df)
        assert isinstance(fig, go.Figure)

    def test_empty(self):
        fig = create_margin_chart(pd.DataFrame())
        assert isinstance(fig, go.Figure)


# ============================================================================
# 基本面圖表組
# ============================================================================

class TestCreateFundamentalChart:
    def test_with_eps(self):
        fin_df = pd.DataFrame({
            "date": pd.date_range("2023-03-31", periods=4, freq="QE"),
            "type": ["EarningsPerShare"] * 4,
            "value": [8.5, 9.0, 9.5, 10.0],
        })
        figs = create_fundamental_chart(fin_df, pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
        assert "eps" in figs
        assert isinstance(figs["eps"], go.Figure)

    def test_with_revenue(self):
        rev_df = pd.DataFrame({
            "date": pd.date_range("2023-01-01", periods=6, freq="MS"),
            "revenue": [1.5e8, 1.6e8, 1.7e8, 1.55e8, 1.65e8, 1.8e8],
        })
        figs = create_fundamental_chart(pd.DataFrame(), rev_df, pd.DataFrame(), pd.DataFrame())
        assert "revenue" in figs

    def test_with_per(self):
        per_df = pd.DataFrame({
            "date": pd.date_range("2023-01-01", periods=100, freq="B"),
            "per": np.random.uniform(15, 25, 100),
        })
        figs = create_fundamental_chart(pd.DataFrame(), pd.DataFrame(), per_df, pd.DataFrame())
        assert "per" in figs

    def test_with_dividend(self):
        div_df = pd.DataFrame({
            "date": pd.date_range("2020-01-01", periods=4, freq="6ME"),
            "dividend": [10.0, 6.0, 11.0, 6.5],
        })
        figs = create_fundamental_chart(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), div_df)
        assert "dividend" in figs

    def test_all_empty(self):
        figs = create_fundamental_chart(
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        )
        assert isinstance(figs, dict)
        assert len(figs) == 0


# ============================================================================
# 權益曲線
# ============================================================================

class TestCreateEquityCurve:
    def test_basic(self, equity_series):
        fig = create_equity_curve(equity_series)
        assert isinstance(fig, go.Figure)

    def test_with_benchmark(self, equity_series):
        benchmark = equity_series * 0.95
        fig = create_equity_curve(equity_series, benchmark=benchmark)
        assert isinstance(fig, go.Figure)

    def test_with_drawdown(self, equity_series):
        peak = equity_series.cummax()
        dd = (equity_series - peak) / peak
        fig = create_equity_curve(equity_series, drawdown=dd)
        assert isinstance(fig, go.Figure)


# ============================================================================
# 月報酬率熱力圖
# ============================================================================

class TestCreateMonthlyHeatmap:
    def test_basic(self, monthly_returns):
        fig = create_monthly_heatmap(monthly_returns)
        assert isinstance(fig, go.Figure)

    def test_empty(self):
        fig = create_monthly_heatmap(pd.Series(dtype=float))
        assert isinstance(fig, go.Figure)


# ============================================================================
# 相關性矩陣
# ============================================================================

class TestCreateCorrelationHeatmap:
    def test_basic(self):
        np.random.seed(42)
        data = pd.DataFrame(np.random.randn(50, 3), columns=["A", "B", "C"])
        corr = data.corr()
        fig = create_correlation_heatmap(corr)
        assert isinstance(fig, go.Figure)


# ============================================================================
# Treemap
# ============================================================================

class TestCreateTreemap:
    def test_basic(self):
        data = pd.DataFrame({
            "name": ["台積電", "鴻海", "聯發科"],
            "market_cap": [17e12, 1.5e12, 1.2e12],
            "change_pct": [1.5, -0.8, 2.3],
        })
        fig = create_treemap(data, "name", "market_cap", "change_pct")
        assert isinstance(fig, go.Figure)

    def test_empty(self):
        fig = create_treemap(pd.DataFrame(), "a", "b", "c")
        assert isinstance(fig, go.Figure)


# ============================================================================
# 經濟指標圖
# ============================================================================

class TestCreateEconomicIndicatorChart:
    def test_basic(self):
        data = pd.DataFrame({
            "date": pd.date_range("2020-01-01", periods=36, freq="MS"),
            "value": np.random.randn(36) * 2 + 100,
        })
        config = {"name": "CPI", "unit": "Index"}
        fig = create_economic_indicator_chart(data, config)
        assert isinstance(fig, go.Figure)

    def test_empty(self):
        config = {"name": "CPI", "unit": "Index"}
        fig = create_economic_indicator_chart(pd.DataFrame(), config)
        assert isinstance(fig, go.Figure)


# ============================================================================
# 殖利率利差圖
# ============================================================================

class TestCreateYieldSpreadChart:
    def test_basic(self):
        dates = pd.date_range("2020-01-01", periods=100, freq="B")
        df_10y = pd.DataFrame({
            "date": dates,
            "value": np.random.uniform(3.0, 5.0, 100),
        })
        df_2y = pd.DataFrame({
            "date": dates,
            "value": np.random.uniform(2.0, 4.0, 100),
        })
        fig = create_yield_spread_chart(df_10y, df_2y)
        assert isinstance(fig, go.Figure)

    def test_empty(self):
        fig = create_yield_spread_chart(pd.DataFrame(), pd.DataFrame())
        assert isinstance(fig, go.Figure)

    def test_only_10y(self):
        dates = pd.date_range("2020-01-01", periods=50, freq="B")
        df_10y = pd.DataFrame({
            "date": dates,
            "value": np.random.uniform(3.0, 5.0, 50),
        })
        fig = create_yield_spread_chart(df_10y, pd.DataFrame())
        assert isinstance(fig, go.Figure)
