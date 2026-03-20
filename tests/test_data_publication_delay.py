"""
資料公布延遲常數測試

覆蓋：
  - 常數存在且完整
  - 延遲值合理範圍
  - 延遲偏移工具函式正確
"""

import pandas as pd
import pytest

from core.constants import DATA_PUBLICATION_DELAY, apply_publication_delay


class TestPublicationDelayConstants:
    """延遲常數完整性"""

    def test_all_data_tables_have_delay(self):
        expected_tables = {
            "daily_price", "chip_institutional", "chip_margin",
            "chip_holding_pct", "chip_securities_lending", "chip_short_sale",
            "stock_per", "month_revenue", "financial_reports",
            "dividend_history", "market_value",
        }
        for table in expected_tables:
            assert table in DATA_PUBLICATION_DELAY, f"{table} 缺少延遲定義"

    def test_daily_price_has_zero_delay(self):
        assert DATA_PUBLICATION_DELAY["daily_price"] == 0

    def test_month_revenue_delay_is_10(self):
        assert DATA_PUBLICATION_DELAY["month_revenue"] == 10

    def test_financial_reports_delay_is_45(self):
        assert DATA_PUBLICATION_DELAY["financial_reports"] == 45

    def test_all_delays_are_non_negative(self):
        for table, delay in DATA_PUBLICATION_DELAY.items():
            assert delay >= 0, f"{table} 延遲為負: {delay}"


class TestApplyPublicationDelay:
    """延遲偏移工具函式"""

    def test_zero_delay_returns_unchanged(self):
        df = pd.DataFrame({
            "date": pd.date_range("2025-01-01", periods=5),
            "value": [1, 2, 3, 4, 5],
        })
        result = apply_publication_delay(df, "daily_price")
        pd.testing.assert_frame_equal(result, df)

    def test_delay_shifts_dates_forward(self):
        df = pd.DataFrame({
            "date": [pd.Timestamp("2025-02-28")],
            "revenue": [1000],
        })
        result = apply_publication_delay(df, "month_revenue")
        # 月營收延遲 10 天：2025-02-28 → 2025-03-10
        assert result.iloc[0]["date"] == pd.Timestamp("2025-03-10")

    def test_delay_preserves_other_columns(self):
        df = pd.DataFrame({
            "date": [pd.Timestamp("2025-03-31")],
            "value": [42.0],
            "type": ["EPS"],
        })
        result = apply_publication_delay(df, "financial_reports")
        assert result.iloc[0]["value"] == 42.0
        assert result.iloc[0]["type"] == "EPS"

    def test_unknown_table_returns_unchanged(self):
        df = pd.DataFrame({
            "date": [pd.Timestamp("2025-01-01")],
            "value": [1],
        })
        result = apply_publication_delay(df, "unknown_table")
        pd.testing.assert_frame_equal(result, df)

    def test_empty_df_returns_empty(self):
        df = pd.DataFrame(columns=["date", "value"])
        result = apply_publication_delay(df, "month_revenue")
        assert result.empty
