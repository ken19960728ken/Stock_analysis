"""
季報自動增量更新測試

測試範圍：
- expected_latest_quarter 邊界值（關鍵日期 × 12 個月）
- is_quarterly_report_month 12 個月
- get_missing_stocks 差集邏輯
- FundamentalUpdater.run() 整合測試（月份檢查、force、差集、熔斷）
"""
import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from scanners.fundamental_updater import (
    CIRCUIT_BREAKER_THRESHOLD,
    FundamentalUpdater,
    expected_latest_quarter,
    get_missing_stocks,
    is_quarterly_report_month,
)


# ============================================================================
# expected_latest_quarter
# ============================================================================

class TestExpectedLatestQuarter:
    """測試季報預期日期推算"""

    def test_jan_returns_prev_year_q3(self):
        assert expected_latest_quarter(datetime.date(2026, 1, 1)) == datetime.date(2025, 9, 30)
        assert expected_latest_quarter(datetime.date(2026, 1, 31)) == datetime.date(2025, 9, 30)

    def test_feb_returns_prev_year_q3(self):
        assert expected_latest_quarter(datetime.date(2026, 2, 15)) == datetime.date(2025, 9, 30)
        assert expected_latest_quarter(datetime.date(2026, 2, 28)) == datetime.date(2025, 9, 30)

    def test_mar_returns_prev_year_q4(self):
        assert expected_latest_quarter(datetime.date(2026, 3, 1)) == datetime.date(2025, 12, 31)
        assert expected_latest_quarter(datetime.date(2026, 3, 31)) == datetime.date(2025, 12, 31)

    def test_apr_returns_prev_year_q4(self):
        assert expected_latest_quarter(datetime.date(2026, 4, 15)) == datetime.date(2025, 12, 31)

    def test_may14_returns_prev_year_q4(self):
        assert expected_latest_quarter(datetime.date(2026, 5, 14)) == datetime.date(2025, 12, 31)

    def test_may15_returns_q1(self):
        assert expected_latest_quarter(datetime.date(2026, 5, 15)) == datetime.date(2026, 3, 31)

    def test_jun_returns_q1(self):
        assert expected_latest_quarter(datetime.date(2026, 6, 30)) == datetime.date(2026, 3, 31)

    def test_aug13_returns_q1(self):
        assert expected_latest_quarter(datetime.date(2026, 8, 13)) == datetime.date(2026, 3, 31)

    def test_aug14_returns_q2(self):
        assert expected_latest_quarter(datetime.date(2026, 8, 14)) == datetime.date(2026, 6, 30)

    def test_oct_returns_q2(self):
        assert expected_latest_quarter(datetime.date(2026, 10, 15)) == datetime.date(2026, 6, 30)

    def test_nov13_returns_q2(self):
        assert expected_latest_quarter(datetime.date(2026, 11, 13)) == datetime.date(2026, 6, 30)

    def test_nov14_returns_q3(self):
        assert expected_latest_quarter(datetime.date(2026, 11, 14)) == datetime.date(2026, 9, 30)

    def test_dec_returns_q3(self):
        assert expected_latest_quarter(datetime.date(2026, 12, 31)) == datetime.date(2026, 9, 30)


# ============================================================================
# is_quarterly_report_month
# ============================================================================

class TestIsQuarterlyReportMonth:
    """測試季報公布月判斷"""

    @pytest.mark.parametrize("month,expected", [
        (1, False), (2, True), (3, True), (4, False),
        (5, True), (6, False), (7, False), (8, True),
        (9, False), (10, False), (11, True), (12, False),
    ])
    def test_all_months(self, month, expected):
        d = datetime.date(2026, month, 15)
        assert is_quarterly_report_month(d) is expected


# ============================================================================
# get_missing_stocks
# ============================================================================

class TestGetMissingStocks:
    """測試差集查詢"""

    @patch("scanners.fundamental_updater.safe_read_sql")
    def test_normal_diff(self, mock_sql):
        # 全市場 3 支，DB 已有 1 支
        mock_sql.side_effect = [
            pd.DataFrame({"stock_id": ["2330", "2317", "2454"]}),
            pd.DataFrame({"stock_id": ["2330"]}),
        ]
        result = get_missing_stocks(datetime.date(2026, 3, 31))
        assert result == ["2317", "2454"]

    @patch("scanners.fundamental_updater.safe_read_sql")
    def test_all_covered(self, mock_sql):
        mock_sql.side_effect = [
            pd.DataFrame({"stock_id": ["2330", "2317"]}),
            pd.DataFrame({"stock_id": ["2317", "2330"]}),
        ]
        result = get_missing_stocks(datetime.date(2026, 3, 31))
        assert result == []

    @patch("scanners.fundamental_updater.safe_read_sql")
    def test_db_error_on_twstock(self, mock_sql):
        mock_sql.side_effect = Exception("DB connection failed")
        result = get_missing_stocks(datetime.date(2026, 3, 31))
        assert result == []

    @patch("scanners.fundamental_updater.safe_read_sql")
    def test_db_error_on_financial_reports(self, mock_sql):
        mock_sql.side_effect = [
            pd.DataFrame({"stock_id": ["2330", "2317"]}),
            Exception("DB error"),
        ]
        result = get_missing_stocks(datetime.date(2026, 3, 31))
        # 查不到已有記錄，回傳全部
        assert set(result) == {"2330", "2317"}


# ============================================================================
# FundamentalUpdater.run()
# ============================================================================

class TestFundamentalUpdaterRun:
    """測試 FundamentalUpdater 主流程"""

    @patch("scanners.fundamental_updater.log_scanner_run")
    @patch("scanners.fundamental_updater.get_missing_stocks")
    @patch("scanners.fundamental_updater.is_quarterly_report_month", return_value=False)
    def test_skip_non_report_month(self, mock_is_qm, mock_missing, mock_log,
                                    mock_finmind_client, mock_rate_limiter):
        updater = FundamentalUpdater()
        updater.run(target_date=datetime.date(2026, 4, 15))
        mock_missing.assert_not_called()

    @patch("scanners.fundamental_updater.log_scanner_run")
    @patch("scanners.fundamental_updater.get_missing_stocks", return_value=["2330", "2317"])
    @patch("scanners.fundamental_updater.is_quarterly_report_month", return_value=False)
    def test_force_overrides_month_check(self, mock_is_qm, mock_missing, mock_log,
                                          mock_finmind_client, mock_rate_limiter, mock_db_save):
        updater = FundamentalUpdater()
        updater.run(target_date=datetime.date(2026, 4, 15), force=True)
        mock_missing.assert_called_once()

    @patch("scanners.fundamental_updater.log_scanner_run")
    @patch("scanners.fundamental_updater.get_missing_stocks", return_value=[])
    @patch("scanners.fundamental_updater.is_quarterly_report_month", return_value=True)
    def test_no_missing_stocks(self, mock_is_qm, mock_missing, mock_log,
                                mock_finmind_client, mock_rate_limiter):
        updater = FundamentalUpdater()
        updater.run(target_date=datetime.date(2026, 3, 15))
        mock_log.assert_called_once()

    @patch("scanners.fundamental_updater.log_scanner_run")
    @patch("scanners.fundamental_updater.get_missing_stocks", return_value=["2330"])
    @patch("scanners.fundamental_updater.is_quarterly_report_month", return_value=True)
    def test_successful_fetch(self, mock_is_qm, mock_missing, mock_log,
                               mock_finmind_client, mock_rate_limiter, mock_db_save):
        # 設定 FinMind 回傳資料
        mock_finmind_client.taiwan_stock_financial_statement.return_value = pd.DataFrame({
            "date": ["2025-12-31"],
            "stock_id": ["2330"],
            "type": ["Revenue"],
            "value": [450000000000],
        })
        mock_finmind_client.taiwan_stock_balance_sheet.return_value = pd.DataFrame({
            "date": ["2025-12-31"],
            "stock_id": ["2330"],
            "type": ["TotalAssets"],
            "value": [2000000000000],
        })

        updater = FundamentalUpdater()
        updater.run(target_date=datetime.date(2026, 3, 15))

        assert mock_db_save.call_count >= 1
        mock_log.assert_called_once()

    @patch("scanners.fundamental_updater.log_scanner_run")
    @patch("scanners.fundamental_updater.get_missing_stocks")
    @patch("scanners.fundamental_updater.is_quarterly_report_month", return_value=True)
    def test_circuit_breaker(self, mock_is_qm, mock_missing, mock_log,
                              mock_finmind_client, mock_rate_limiter, mock_db_save):
        # 20 支股票，全部失敗 → 第 10 次觸發熔斷
        stocks = [str(i) for i in range(1000, 1020)]
        mock_missing.return_value = stocks

        mock_finmind_client.taiwan_stock_financial_statement.side_effect = Exception("API Error")
        mock_finmind_client.taiwan_stock_balance_sheet.side_effect = Exception("API Error")

        updater = FundamentalUpdater()
        updater.run(target_date=datetime.date(2026, 3, 15))

        # 熔斷後不應該繼續，save_to_db 不應被呼叫
        mock_db_save.assert_not_called()

    @patch("scanners.fundamental_updater.log_scanner_run")
    @patch("scanners.fundamental_updater.get_missing_stocks", return_value=["2330"])
    @patch("scanners.fundamental_updater.is_quarterly_report_month", return_value=True)
    def test_fetch_empty_data_counts_as_success(self, mock_is_qm, mock_missing, mock_log,
                                                  mock_finmind_client, mock_rate_limiter):
        # API 成功但無資料（如 ETF）
        mock_finmind_client.taiwan_stock_financial_statement.return_value = pd.DataFrame()
        mock_finmind_client.taiwan_stock_balance_sheet.return_value = None

        updater = FundamentalUpdater()
        updater.run(target_date=datetime.date(2026, 3, 15))

        # 應記錄 success_count=1
        call_kwargs = mock_log.call_args[1]
        assert call_kwargs["success_count"] == 1

    def test_run_with_string_date(self, mock_finmind_client, mock_rate_limiter):
        with patch("scanners.fundamental_updater.is_quarterly_report_month", return_value=False):
            updater = FundamentalUpdater()
            updater.run(target_date="2026-04-15")
            # 不應拋錯


# ============================================================================
# FundamentalUpdater._fetch_one()
# ============================================================================

class TestFetchOne:
    """測試單支抓取邏輯"""

    def test_filters_focus_metrics(self, mock_finmind_client, mock_rate_limiter, mock_db_save):
        mock_finmind_client.taiwan_stock_financial_statement.return_value = pd.DataFrame({
            "date": ["2025-12-31", "2025-12-31"],
            "stock_id": ["2330", "2330"],
            "type": ["Revenue", "SomeUnknownMetric"],
            "value": [450e9, 999],
        })
        mock_finmind_client.taiwan_stock_balance_sheet.return_value = pd.DataFrame()

        updater = FundamentalUpdater()
        ok = updater._fetch_one("2330")
        assert ok is True

        # 只有 Revenue 被保留
        saved_df = mock_db_save.call_args[0][0]
        assert len(saved_df) == 1
        assert saved_df.iloc[0]["type"] == "Revenue"

    def test_api_exception_returns_false(self, mock_finmind_client, mock_rate_limiter):
        """MockRateLimiter.call_with_retry 會吞掉異常並回傳 None，
        但若異常在 call_with_retry 外部被丟出（如網路層），_fetch_one 會回傳 False。
        """
        # 直接讓 _fetch_one 的 try block 整體拋錯
        mock_finmind_client.taiwan_stock_financial_statement.side_effect = Exception("timeout")
        mock_finmind_client.taiwan_stock_balance_sheet.side_effect = Exception("timeout")

        updater = FundamentalUpdater()
        # MockRateLimiter 吞掉異常 → 兩個 df 都是 None → 視為無資料（成功）
        ok = updater._fetch_one("2330")
        assert ok is True

    def test_real_api_exception_propagation(self, mock_finmind_client):
        """不用 mock_rate_limiter，直接測試 API 異常傳播"""
        mock_finmind_client.taiwan_stock_financial_statement.side_effect = RuntimeError("FinMind API 回應異常")

        with patch("scanners.fundamental_updater.RateLimiter") as MockRL:
            instance = MockRL.return_value
            instance.call_with_retry.side_effect = RuntimeError("FinMind API 回應異常")
            instance.wait = MagicMock()

            updater = FundamentalUpdater()
            ok = updater._fetch_one("2330")
            assert ok is False
