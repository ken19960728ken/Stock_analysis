"""
Paper Trading 報告模組測試
"""

import numpy as np
import pandas as pd
import pytest

from scripts.paper_report import (
    _fmt,
    _money,
    _pct,
    check_and_send_alerts,
    is_week_end,
)


# ===================================================================
# 格式化工具
# ===================================================================

class TestFormatters:

    def test_money_positive(self):
        assert _money(1000000) == "+1,000,000"

    def test_money_negative(self):
        assert _money(-50000) == "-50,000"

    def test_money_zero(self):
        assert _money(0) == "0"

    def test_money_none(self):
        assert _money(None) == "-"

    def test_money_nan(self):
        assert _money(np.nan) == "-"

    def test_pct_normal(self):
        assert _pct(0.05) == "+5.00%"

    def test_pct_negative(self):
        assert _pct(-0.03) == "-3.00%"

    def test_pct_none(self):
        assert _pct(None) == "-"

    def test_fmt_normal(self):
        assert _fmt(1.234) == "1.234"


# ===================================================================
# 週末判斷
# ===================================================================

class TestIsWeekEnd:

    def test_friday(self):
        assert is_week_end("2026-03-27") is True  # 週五

    def test_monday(self):
        assert is_week_end("2026-03-23") is False  # 週一

    def test_wednesday(self):
        assert is_week_end("2026-03-25") is False


# ===================================================================
# 告警
# ===================================================================

class TestAlerts:

    def test_no_alerts(self, monkeypatch):
        monkeypatch.setattr("scripts.paper_report.send_alert_email", lambda **kw: True)
        check_and_send_alerts([])  # 不應報錯

    def test_critical_alert(self, monkeypatch):
        sent = []
        monkeypatch.setattr(
            "scripts.paper_report.send_alert_email",
            lambda **kw: sent.append(kw) or True,
        )
        alerts = [
            {"type": "drawdown_liquidate", "severity": "critical",
             "message": "回撤 -21% 觸發清倉"},
        ]
        check_and_send_alerts(alerts)
        assert len(sent) == 1
        assert sent[0]["severity"] == "critical"

    def test_warning_alert(self, monkeypatch):
        sent = []
        monkeypatch.setattr(
            "scripts.paper_report.send_alert_email",
            lambda **kw: sent.append(kw) or True,
        )
        alerts = [
            {"type": "strategy_pause", "severity": "warning",
             "message": "RSI 反轉連虧 5 次"},
        ]
        check_and_send_alerts(alerts)
        assert len(sent) == 1
        assert sent[0]["severity"] == "warning"
