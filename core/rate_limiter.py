import random
import time

from core.finmind_client import get_fm_token
from core.logger import setup_logger

logger = setup_logger("rate_limiter")


# ============================================================================
# FinMind API 預算控制（module-level，所有 scanner 共享）
# ============================================================================

class BudgetExhaustedError(Exception):
    """FinMind API 配額已用盡"""
    pass


_budget_remaining = None  # None = 不限制


def set_budget(limit):
    """設定本輪 FinMind API 呼叫預算"""
    global _budget_remaining
    _budget_remaining = limit
    logger.info(f"FinMind API 預算已設定: {limit} 次")


def get_budget_remaining():
    """查詢剩餘預算，None 表示不限制"""
    return _budget_remaining


def reset_budget():
    """重置預算（週期結束時）"""
    global _budget_remaining
    _budget_remaining = None


def _consume_budget():
    """內部使用：消耗一次預算"""
    global _budget_remaining
    if _budget_remaining is not None:
        _budget_remaining -= 1


# ============================================================================
# RateLimiter
# ============================================================================

class RateLimiter:
    """統一限速器，根據有無 Token 與 API 來源自動調整延遲"""

    def __init__(self, source="finmind"):
        """
        source: "finmind" 或 "yahoo"
        """
        self.source = source
        self._configure()

    def _configure(self):
        if self.source == "yahoo":
            self.delay_min = 0.8
            self.delay_max = 1.5
        elif get_fm_token():
            self.delay_min = 1.5
            self.delay_max = 2.5
        else:
            self.delay_min = 4.0
            self.delay_max = 6.0

    def wait(self):
        """正常請求間的延遲"""
        time.sleep(random.uniform(self.delay_min, self.delay_max))

    def backoff(self, attempt=1):
        """429 重試退避，每次 10 秒"""
        wait_time = 10 * attempt
        logger.warning(f"觸發限速，休息 {wait_time} 秒...")
        time.sleep(wait_time)

    def call_with_retry(self, fn, max_retries=3):
        """
        執行 fn()，遇到 429 自動重試。
        返回 fn() 的結果，若全部重試失敗則返回 None。

        FinMind 來源會檢查並消耗預算，Yahoo 不受影響。
        """
        if self.source == "finmind" and _budget_remaining is not None:
            if _budget_remaining <= 0:
                raise BudgetExhaustedError("FinMind API 預算已用盡")

        for attempt in range(1, max_retries + 1):
            try:
                result = fn()
                if self.source == "finmind":
                    _consume_budget()
                return result
            except KeyError as e:
                if str(e) == "'data'":
                    raise RuntimeError(
                        "FinMind API 回應異常（可能配額已用盡），請稍後再試"
                    ) from e
                raise
            except Exception as e:
                if "429" in str(e) and attempt < max_retries:
                    self.backoff(attempt)
                else:
                    raise
        return None
