import random
import time

from core.finmind_client import get_fm_token
from core.logger import setup_logger

logger = setup_logger("rate_limiter")


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
        """
        for attempt in range(1, max_retries + 1):
            try:
                return fn()
            except Exception as e:
                if "429" in str(e) and attempt < max_retries:
                    self.backoff(attempt)
                else:
                    raise
        return None
