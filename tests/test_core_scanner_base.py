"""core/scanner_base.py 測試"""

from unittest.mock import MagicMock, patch

import pytest

from core.rate_limiter import BudgetExhaustedError
from core.scanner_base import BaseScanner


class ConcreteScanner(BaseScanner):
    """測試用具象 Scanner"""
    name = "TestScanner"
    resume_tables = []

    def __init__(self, targets=None, fetch_results=None):
        self._targets = targets if targets is not None else ["2330", "2317", "2454"]
        self._fetch_results = fetch_results if fetch_results is not None else {}
        self._fetch_calls = []

    def get_targets(self):
        return self._targets

    def fetch_one(self, target):
        self._fetch_calls.append(target)
        sid = self._get_stock_id(target)
        if sid in self._fetch_results:
            result = self._fetch_results[sid]
            if isinstance(result, Exception):
                raise result
            return result
        return True


@pytest.fixture
def mock_scanner_deps(monkeypatch):
    """Mock 掉 scanner_base 內部依賴"""
    monkeypatch.setattr("core.scanner_base.all_indexed", MagicMock(return_value=False))
    monkeypatch.setattr("core.scanner_base.close_index", MagicMock())
    monkeypatch.setattr("core.scanner_base.dispose_engine", MagicMock())


class TestBaseScannerScan:
    def test_scan_all_success(self, mock_scanner_deps):
        scanner = ConcreteScanner(targets=["2330", "2317"])
        scanner.scan()
        assert scanner._fetch_calls == ["2330", "2317"]

    def test_scan_empty_targets(self, mock_scanner_deps):
        scanner = ConcreteScanner(targets=[])
        scanner.scan()  # should not raise
        assert scanner._fetch_calls == []

    def test_scan_with_failures(self, mock_scanner_deps):
        scanner = ConcreteScanner(
            targets=["2330", "2317"],
            fetch_results={"2330": False, "2317": True},
        )
        scanner.scan()
        assert len(scanner._fetch_calls) == 2

    def test_scan_with_exception(self, mock_scanner_deps):
        scanner = ConcreteScanner(
            targets=["2330", "2317"],
            fetch_results={"2330": ValueError("fetch error")},
        )
        scanner.scan()  # should not raise, logs error
        assert len(scanner._fetch_calls) == 2

    def test_budget_exhausted_stops_scan(self, mock_scanner_deps):
        scanner = ConcreteScanner(
            targets=["2330", "2317", "2454"],
            fetch_results={"2330": BudgetExhaustedError("no budget")},
        )
        scanner.scan()
        # Only first target attempted before budget exception stops everything
        assert scanner._fetch_calls == ["2330"]


class TestCircuitBreaker:
    def test_consecutive_failures_triggers_circuit_breaker(self, mock_scanner_deps):
        targets = [str(i) for i in range(15)]
        scanner = ConcreteScanner(
            targets=targets,
            fetch_results={str(i): False for i in range(15)},
        )
        scanner.scan()
        # Should stop after 10 consecutive failures
        assert len(scanner._fetch_calls) == 10

    def test_success_resets_consecutive_counter(self, mock_scanner_deps):
        # 9 failures, then 1 success, then 5 more failures
        targets = [str(i) for i in range(15)]
        results = {}
        for i in range(9):
            results[str(i)] = False
        results["9"] = True
        for i in range(10, 15):
            results[str(i)] = False
        scanner = ConcreteScanner(targets=targets, fetch_results=results)
        scanner.scan()
        # All 15 should be attempted (success at #9 resets counter)
        assert len(scanner._fetch_calls) == 15


class TestResumeSkip:
    def test_skip_indexed_targets(self, monkeypatch):
        monkeypatch.setattr("core.scanner_base.close_index", MagicMock())
        monkeypatch.setattr("core.scanner_base.dispose_engine", MagicMock())
        monkeypatch.setattr(
            "core.scanner_base.all_indexed",
            MagicMock(side_effect=lambda tables, sid: sid == "2330"),
        )
        scanner = ConcreteScanner(targets=["2330", "2317"])
        scanner.resume_tables = ["daily_price"]
        scanner.scan()
        # 2330 should be skipped
        assert scanner._fetch_calls == ["2317"]


class TestGetStockId:
    def test_string_target(self, mock_scanner_deps):
        scanner = ConcreteScanner()
        assert scanner._get_stock_id("2330") == "2330"

    def test_dict_target(self, mock_scanner_deps):
        scanner = ConcreteScanner()
        assert scanner._get_stock_id({"stock_id": "2330", "name": "台積電"}) == "2330"

    def test_dict_without_stock_id(self, mock_scanner_deps):
        scanner = ConcreteScanner()
        target = {"name": "test"}
        result = scanner._get_stock_id(target)
        assert isinstance(result, str)
