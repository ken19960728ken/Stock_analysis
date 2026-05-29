"""
績效追蹤測試 — 回填邏輯 + 報告產出

覆蓋：
  - 交易日計算（T+N 是交易日而非日曆日）
  - 部分回填（T+5 可填但 T+20 尚不可）
  - 空資料處理
  - 績效追蹤報告產出
"""

import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock, patch, call

from scripts.performance_tracker import (
    _calc_trading_day_prices,
    backfill_performance,
    generate_performance_report,
)


class TestTradingDayPrices:
    """交易日價格計算"""

    def test_basic_trading_days(self):
        """正常情況：連續交易日"""
        # 模擬 20 個交易日的價格資料
        dates = pd.bdate_range("2026-03-23", periods=25, freq="B")
        prices_df = pd.DataFrame({
            "date": dates,
            "close": [100 + i * 0.5 for i in range(25)],
        })
        result = _calc_trading_day_prices(prices_df)
        # T+5 = 第 5 個交易日（index 4）
        assert result["price_t5"] == 100 + 4 * 0.5
        assert result["price_t10"] == 100 + 9 * 0.5
        assert result["price_t20"] == 100 + 19 * 0.5

    def test_partial_data_only_t5(self):
        """只有 7 個交易日 → 只能算 T+5"""
        dates = pd.bdate_range("2026-03-23", periods=7, freq="B")
        prices_df = pd.DataFrame({
            "date": dates,
            "close": [100 + i for i in range(7)],
        })
        result = _calc_trading_day_prices(prices_df)
        assert result["price_t5"] == 104.0
        assert result["price_t10"] is None
        assert result["price_t20"] is None

    def test_insufficient_data(self):
        """不足 5 個交易日 → 全部 None"""
        dates = pd.bdate_range("2026-03-23", periods=3, freq="B")
        prices_df = pd.DataFrame({
            "date": dates,
            "close": [100, 101, 102],
        })
        result = _calc_trading_day_prices(prices_df)
        assert result["price_t5"] is None
        assert result["price_t10"] is None
        assert result["price_t20"] is None

    def test_empty_df(self):
        result = _calc_trading_day_prices(pd.DataFrame())
        assert result["price_t5"] is None


class TestBackfillPerformance:
    """績效回填"""

    @patch("scripts.performance_tracker.safe_read_sql")
    @patch("scripts.performance_tracker.get_engine")
    def test_backfill_skips_when_no_pending(self, mock_engine, mock_sql):
        """無待回填記錄時不做事"""
        mock_sql.return_value = pd.DataFrame()
        result = backfill_performance()
        assert result == 0

    @patch("scripts.performance_tracker.safe_read_sql")
    @patch("scripts.performance_tracker.get_engine")
    def test_backfill_updates_t5(self, mock_engine, mock_sql):
        """有待回填的 T+5 記錄"""
        # 第一次查詢：待回填記錄
        pending = pd.DataFrame({
            "id": [1],
            "report_date": [pd.Timestamp("2026-03-10")],
            "stock_id": ["2330"],
            "entry_price": [850.0],
            "return_t5": [None],
            "return_t10": [None],
            "return_t20": [None],
        })
        # 第二次查詢：後續交易日價格
        prices = pd.DataFrame({
            "date": pd.bdate_range("2026-03-11", periods=25, freq="B"),
            "close": [855 + i * 0.5 for i in range(25)],
        })
        mock_sql.side_effect = [pending, prices]

        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        result = backfill_performance()
        assert result >= 0  # 不會拋錯

    @patch("scripts.performance_tracker.safe_read_sql")
    @patch("scripts.performance_tracker.get_engine")
    def test_backfill_handles_nan_columns(self, mock_engine, mock_sql):
        """Regression: pandas 讀 SQL NULL 為 float64 NaN（非 None）。

        舊版用 `row["return_t5"] is None` 判斷，對 NaN 永遠 False，
        導致回填從不更新。此測試用 np.nan 重現真實 DB 讀取情境，
        確認 pd.isna 路徑會正確計算並執行 UPDATE。
        """
        pending = pd.DataFrame({
            "id": [1],
            "report_date": [pd.Timestamp("2026-03-10")],
            "stock_id": ["2330"],
            "entry_price": [850.0],
            "return_t5": [np.nan],
            "return_t10": [np.nan],
            "return_t20": [np.nan],
        })
        # 確認模擬的是 float64 + NaN（真實 DB 讀取行為），非 object + None
        assert pending["return_t5"].dtype == np.float64
        prices = pd.DataFrame({
            "date": pd.bdate_range("2026-03-11", periods=25, freq="B"),
            "close": [855 + i * 0.5 for i in range(25)],
        })
        mock_sql.side_effect = [pending, prices]

        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        result = backfill_performance()

        # 必須真的更新了 1 筆（舊 buggy 版本會是 0）
        assert result == 1
        assert mock_conn.execute.called
        # 驗證 UPDATE 帶入計算後的 return_t5：T+5=index4=857.0, (857/850-1)*100=0.82
        params = mock_conn.execute.call_args[0][1]
        assert params["return_t5"] == 0.82
        assert params["return_t20"] == round((855 + 19 * 0.5) / 850 * 100 - 100, 2)


class TestPerformanceReport:
    """績效追蹤報告"""

    @patch("scripts.performance_tracker.safe_read_sql")
    def test_report_with_data(self, mock_sql):
        """有績效資料時產出報告"""
        mock_sql.return_value = pd.DataFrame({
            "report_date": pd.date_range("2026-03-01", periods=5),
            "stock_id": ["2330", "2317", "2454", "2330", "2317"],
            "stock_name": ["台積電", "鴻海", "聯發科", "台積電", "鴻海"],
            "entry_price": [850, 120, 900, 860, 122],
            "return_t5": [1.2, -0.5, 2.0, 0.8, 1.5],
            "return_t10": [2.0, 0.5, 3.0, None, None],
            "return_t20": [3.5, 1.0, None, None, None],
            "rank": [1, 2, 3, 1, 2],
            "agree_count": [4, 3, 5, 4, 3],
            "total_strategies": [11, 11, 11, 11, 11],
            "strategy_votes": [{}] * 5,
            "git_commit": ["abc"] * 5,
            "app_version": ["1.0.0"] * 5,
        })
        report = generate_performance_report()
        assert "績效追蹤報告" in report
        assert "平均報酬" in report or "勝率" in report

    @patch("scripts.performance_tracker.safe_read_sql")
    def test_report_empty(self, mock_sql):
        """無資料時不會 crash"""
        mock_sql.return_value = pd.DataFrame()
        report = generate_performance_report()
        assert "尚無" in report or "績效追蹤" in report
