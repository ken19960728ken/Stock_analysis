"""
告警管理測試 — 執行日誌記錄 + 告警升級

覆蓋：
  - _build_run_log_row 建構正確記錄
  - 狀態判斷邏輯（success / partial / failed）
  - 告警升級（連續失敗判斷）
  - 空資料處理
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd
import pytest

from core.alert_manager import (
    log_scanner_run,
    check_alert_escalation,
    _build_run_log_row,
)


class TestBuildRunLogRow:
    """建構執行日誌記錄"""

    def test_partial_status(self):
        row = _build_run_log_row(
            scanner_name="price",
            started_at=datetime(2026, 3, 20, 10, 30, 0, tzinfo=timezone.utc),
            finished_at=datetime(2026, 3, 20, 10, 35, 0, tzinfo=timezone.utc),
            total_targets=1800,
            success_count=1750,
            skip_count=30,
            fail_count=20,
        )
        assert row["scanner_name"] == "price"
        assert row["status"] == "partial"
        assert row["duration_sec"] == 300.0
        assert row["run_date"] == "2026-03-20"

    def test_all_success_status(self):
        row = _build_run_log_row(
            scanner_name="price",
            started_at=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc),
            finished_at=datetime(2026, 3, 20, 10, 5, tzinfo=timezone.utc),
            total_targets=100,
            success_count=80,
            skip_count=20,
            fail_count=0,
        )
        assert row["status"] == "success"

    def test_all_fail_status(self):
        row = _build_run_log_row(
            scanner_name="chip",
            started_at=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc),
            finished_at=datetime(2026, 3, 20, 10, 1, tzinfo=timezone.utc),
            total_targets=100,
            success_count=0,
            skip_count=0,
            fail_count=100,
            error_message="API quota exceeded",
        )
        assert row["status"] == "failed"
        assert row["error_message"] == "API quota exceeded"

    def test_zero_targets_success(self):
        row = _build_run_log_row(
            scanner_name="daily_report",
            started_at=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc),
            finished_at=datetime(2026, 3, 20, 10, 2, tzinfo=timezone.utc),
            total_targets=0,
            success_count=0,
            skip_count=0,
            fail_count=0,
        )
        assert row["status"] == "success"

    def test_duration_calculation(self):
        row = _build_run_log_row(
            scanner_name="valuation",
            started_at=datetime(2026, 3, 20, 10, 0, 0, tzinfo=timezone.utc),
            finished_at=datetime(2026, 3, 20, 10, 0, 45, tzinfo=timezone.utc),
            total_targets=50,
            success_count=50,
        )
        assert row["duration_sec"] == 45.0

    def test_no_finished_at(self):
        row = _build_run_log_row(
            scanner_name="price",
            started_at=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc),
            total_targets=100,
        )
        assert row["duration_sec"] is None
        assert row["finished_at"] is None


class TestLogScannerRun:
    """記錄執行日誌"""

    @patch("core.alert_manager.save_to_db")
    def test_calls_save_to_db(self, mock_save):
        mock_save.return_value = True
        result = log_scanner_run(
            scanner_name="price",
            started_at=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc),
            finished_at=datetime(2026, 3, 20, 10, 5, tzinfo=timezone.utc),
            total_targets=100,
            success_count=100,
        )
        assert result is True
        mock_save.assert_called_once()
        call_args = mock_save.call_args
        assert call_args[0][1] == "scanner_run_log"

    @patch("core.alert_manager.save_to_db")
    def test_db_failure_returns_false(self, mock_save):
        mock_save.side_effect = Exception("connection error")
        result = log_scanner_run(
            scanner_name="price",
            started_at=datetime(2026, 3, 20, 10, 0, tzinfo=timezone.utc),
        )
        assert result is False


class TestCheckAlertEscalation:
    """告警升級邏輯"""

    @patch("core.alert_manager.safe_read_sql")
    def test_no_recent_runs_no_alert(self, mock_sql):
        mock_sql.return_value = pd.DataFrame()
        level = check_alert_escalation("price")
        assert level is None

    @patch("core.alert_manager.safe_read_sql")
    def test_all_success_no_alert(self, mock_sql):
        mock_sql.return_value = pd.DataFrame({
            "status": ["success", "success", "success"],
            "started_at": pd.date_range("2026-03-18", periods=3),
        })
        level = check_alert_escalation("price")
        assert level is None

    @patch("core.alert_manager.safe_read_sql")
    def test_one_fail_warning(self, mock_sql):
        mock_sql.return_value = pd.DataFrame({
            "status": ["failed", "success", "success"],
            "started_at": pd.date_range("2026-03-18", periods=3),
        })
        level = check_alert_escalation("price")
        assert level == "warning"

    @patch("core.alert_manager.safe_read_sql")
    def test_three_consecutive_fails_critical(self, mock_sql):
        mock_sql.return_value = pd.DataFrame({
            "status": ["failed", "failed", "failed", "success"],
            "started_at": pd.date_range("2026-03-17", periods=4),
        })
        level = check_alert_escalation("price")
        assert level == "critical"

    @patch("core.alert_manager.safe_read_sql")
    def test_partial_not_counted_as_fail(self, mock_sql):
        mock_sql.return_value = pd.DataFrame({
            "status": ["partial", "success"],
            "started_at": pd.date_range("2026-03-19", periods=2),
        })
        level = check_alert_escalation("price")
        assert level is None
