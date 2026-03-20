"""
資料健檢測試

覆蓋：
  - DB 連線檢查
  - 資料最新日期偵測
  - 整體狀態判斷邏輯
  - 告警內文格式
  - 空資料 / DB 斷線處理
"""

from datetime import date
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from core.health_check import run_health_check, format_alert_body, HealthCheckResult


class TestHealthCheckResult:
    """HealthCheckResult 結構"""

    def test_default_values(self):
        r = HealthCheckResult()
        assert r.overall_status == "unknown"
        assert r.db_connected is False
        assert r.checks == []

    def test_custom_values(self):
        r = HealthCheckResult(
            check_date="2026-03-20",
            overall_status="healthy",
            db_connected=True,
            data_max_date="2026-03-20",
        )
        assert r.check_date == "2026-03-20"
        assert r.db_connected is True


class TestRunHealthCheck:
    """run_health_check 整合邏輯"""

    @patch("core.health_check.safe_read_sql")
    @patch("core.health_check.get_engine")
    def test_healthy_when_all_ok(self, mock_engine, mock_sql):
        # DB 連線成功
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (1,)
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=mock_conn)
        ctx.__exit__ = MagicMock(return_value=False)
        mock_engine.return_value.connect.return_value = ctx

        today = date.today()
        mock_sql.side_effect = [
            pd.DataFrame({"max_date": [today]}),   # data_max_date
            pd.DataFrame({"cnt": [1800]}),           # daily count
            pd.DataFrame({"cnt": [1800]}),           # median count
            pd.DataFrame({"cnt": [2]}),              # zero volume (< 50, ok)
            pd.DataFrame({"cnt": [0]}),              # abnormal price
            pd.DataFrame(),                          # scanner_run_log
        ]

        result = run_health_check()
        assert result.db_connected is True
        assert result.overall_status == "healthy"
        assert len(result.checks) >= 5

    @patch("core.health_check.get_engine")
    def test_unhealthy_when_db_down(self, mock_engine):
        mock_engine.side_effect = Exception("connection refused")
        result = run_health_check()
        assert result.db_connected is False
        assert result.overall_status == "unhealthy"
        assert any(c["status"] == "critical" for c in result.checks)

    @patch("core.health_check.safe_read_sql")
    @patch("core.health_check.get_engine")
    def test_degraded_when_data_behind(self, mock_engine, mock_sql):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (1,)
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=mock_conn)
        ctx.__exit__ = MagicMock(return_value=False)
        mock_engine.return_value.connect.return_value = ctx

        # 資料落後 10 天
        old_date = date(2026, 3, 10)
        mock_sql.side_effect = [
            pd.DataFrame({"max_date": [old_date]}),
            pd.DataFrame({"cnt": [1800]}),
            pd.DataFrame({"cnt": [1800]}),
            pd.DataFrame({"cnt": [0]}),
            pd.DataFrame({"cnt": [0]}),
            pd.DataFrame(),
        ]

        result = run_health_check()
        assert result.overall_status == "degraded"

    @patch("core.health_check.safe_read_sql")
    @patch("core.health_check.get_engine")
    def test_warning_when_low_count(self, mock_engine, mock_sql):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (1,)
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=mock_conn)
        ctx.__exit__ = MagicMock(return_value=False)
        mock_engine.return_value.connect.return_value = ctx

        today = date.today()
        mock_sql.side_effect = [
            pd.DataFrame({"max_date": [today]}),
            pd.DataFrame({"cnt": [500]}),     # 遠低於中位數
            pd.DataFrame({"cnt": [1800]}),    # 中位數 1800
            pd.DataFrame({"cnt": [0]}),
            pd.DataFrame({"cnt": [0]}),
            pd.DataFrame(),
        ]

        result = run_health_check()
        assert result.overall_status == "degraded"
        count_check = [c for c in result.checks if c["name"] == "資料筆數"]
        assert len(count_check) == 1
        assert count_check[0]["status"] == "warning"


class TestFormatAlertBody:
    """告警內文格式"""

    def test_formats_warning_checks(self):
        checks = [
            {"name": "DB 連線", "status": "ok", "detail": "正常"},
            {"name": "資料筆數", "status": "warning", "detail": "偏差 30%"},
            {"name": "異常價格", "status": "warning", "detail": "25 支"},
        ]
        body = format_alert_body(checks)
        assert "資料筆數" in body
        assert "異常價格" in body
        assert "DB 連線" not in body  # ok 的不應出現

    def test_empty_checks(self):
        body = format_alert_body([])
        assert "異常" in body

    def test_critical_included(self):
        checks = [{"name": "DB 連線", "status": "critical", "detail": "timeout"}]
        body = format_alert_body(checks)
        assert "CRITICAL" in body
        assert "DB 連線" in body
