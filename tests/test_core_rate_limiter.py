"""core/rate_limiter.py 測試"""

from unittest.mock import MagicMock, patch

import pytest

import core.rate_limiter as rl
from core.rate_limiter import (
    BudgetExhaustedError,
    RateLimiter,
    get_budget_remaining,
    reset_budget,
    set_budget,
)


@pytest.fixture(autouse=True)
def reset_budget_state():
    """每個測試前後重置預算"""
    rl._budget_remaining = None
    yield
    rl._budget_remaining = None


# ============================================================================
# 預算控制
# ============================================================================


class TestBudgetControl:
    def test_initial_budget_is_none(self):
        assert get_budget_remaining() is None

    def test_set_budget(self):
        set_budget(100)
        assert get_budget_remaining() == 100

    def test_reset_budget(self):
        set_budget(50)
        reset_budget()
        assert get_budget_remaining() is None

    def test_consume_budget(self):
        set_budget(5)
        rl._consume_budget()
        assert get_budget_remaining() == 4

    def test_consume_without_budget_is_safe(self):
        rl._consume_budget()  # _budget_remaining is None
        assert get_budget_remaining() is None


class TestBudgetExhaustedError:
    def test_is_exception(self):
        assert issubclass(BudgetExhaustedError, Exception)

    def test_message(self):
        err = BudgetExhaustedError("out of budget")
        assert str(err) == "out of budget"


# ============================================================================
# RateLimiter 建構
# ============================================================================


class TestRateLimiterConfig:
    @patch("core.rate_limiter.get_fm_token", return_value="token123")
    def test_finmind_with_token_fast_delay(self, mock_token):
        limiter = RateLimiter("finmind")
        assert limiter.delay_min == 1.5
        assert limiter.delay_max == 2.5

    @patch("core.rate_limiter.get_fm_token", return_value=None)
    def test_finmind_no_token_slow_delay(self, mock_token):
        limiter = RateLimiter("finmind")
        assert limiter.delay_min == 4.0
        assert limiter.delay_max == 6.0

    @patch("core.rate_limiter.get_fm_token", return_value=None)
    def test_yahoo_delay(self, mock_token):
        limiter = RateLimiter("yahoo")
        assert limiter.delay_min == 0.8
        assert limiter.delay_max == 1.5


# ============================================================================
# call_with_retry
# ============================================================================


class TestCallWithRetry:
    @patch("core.rate_limiter.get_fm_token", return_value=None)
    def test_success_returns_result(self, mock_token):
        limiter = RateLimiter("yahoo")
        result = limiter.call_with_retry(lambda: 42)
        assert result == 42

    @patch("core.rate_limiter.get_fm_token", return_value="tok")
    def test_finmind_consumes_budget(self, mock_token):
        set_budget(10)
        limiter = RateLimiter("finmind")
        limiter.call_with_retry(lambda: "ok")
        assert get_budget_remaining() == 9

    @patch("core.rate_limiter.get_fm_token", return_value="tok")
    def test_budget_zero_raises(self, mock_token):
        set_budget(0)
        limiter = RateLimiter("finmind")
        with pytest.raises(BudgetExhaustedError):
            limiter.call_with_retry(lambda: "ok")

    @patch("core.rate_limiter.get_fm_token", return_value=None)
    def test_yahoo_ignores_budget(self, mock_token):
        set_budget(0)
        limiter = RateLimiter("yahoo")
        result = limiter.call_with_retry(lambda: "ok")
        assert result == "ok"

    @patch("core.rate_limiter.get_fm_token", return_value=None)
    @patch("core.rate_limiter.time.sleep")
    def test_429_retries(self, mock_sleep, mock_token):
        call_count = {"n": 0}

        def flaky():
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise Exception("HTTP 429 rate limited")
            return "success"

        limiter = RateLimiter("yahoo")
        result = limiter.call_with_retry(flaky, max_retries=3)
        assert result == "success"
        assert call_count["n"] == 3

    @patch("core.rate_limiter.get_fm_token", return_value=None)
    @patch("core.rate_limiter.time.sleep")
    def test_non_429_raises_immediately(self, mock_sleep, mock_token):
        limiter = RateLimiter("yahoo")
        with pytest.raises(ValueError, match="bad data"):
            limiter.call_with_retry(lambda: (_ for _ in ()).throw(ValueError("bad data")))

    @patch("core.rate_limiter.get_fm_token", return_value=None)
    def test_key_error_data_raises_runtime(self, mock_token):
        def bad_response():
            raise KeyError("data")

        limiter = RateLimiter("yahoo")
        with pytest.raises(RuntimeError, match="FinMind API 回應異常"):
            limiter.call_with_retry(bad_response)


# ============================================================================
# wait / backoff
# ============================================================================


class TestWaitAndBackoff:
    @patch("core.rate_limiter.get_fm_token", return_value=None)
    @patch("core.rate_limiter.time.sleep")
    def test_wait_calls_sleep(self, mock_sleep, mock_token):
        limiter = RateLimiter("yahoo")
        limiter.wait()
        mock_sleep.assert_called_once()
        delay = mock_sleep.call_args[0][0]
        assert 0.8 <= delay <= 1.5

    @patch("core.rate_limiter.get_fm_token", return_value=None)
    @patch("core.rate_limiter.time.sleep")
    def test_backoff_scales_with_attempt(self, mock_sleep, mock_token):
        limiter = RateLimiter("yahoo")
        limiter.backoff(attempt=2)
        mock_sleep.assert_called_once_with(20)

    @patch("core.rate_limiter.get_fm_token", return_value=None)
    @patch("core.rate_limiter.time.sleep")
    def test_backoff_default_attempt(self, mock_sleep, mock_token):
        limiter = RateLimiter("yahoo")
        limiter.backoff()
        mock_sleep.assert_called_once_with(10)
