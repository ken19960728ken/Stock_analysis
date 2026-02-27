"""core/constants.py 測試"""

from core.constants import RISK_FREE_RATE, TRADING_DAYS_PER_YEAR


class TestConstants:
    def test_trading_days_is_int(self):
        assert isinstance(TRADING_DAYS_PER_YEAR, int)

    def test_trading_days_value(self):
        assert TRADING_DAYS_PER_YEAR == 252

    def test_risk_free_rate_is_float(self):
        assert isinstance(RISK_FREE_RATE, float)

    def test_risk_free_rate_value(self):
        assert RISK_FREE_RATE == 0.015

    def test_risk_free_rate_range(self):
        assert 0 <= RISK_FREE_RATE <= 0.1
