"""core/local_index.py 測試 — 使用 tmp_path 的臨時 SQLite"""

import os
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

import core.local_index as li


@pytest.fixture(autouse=True)
def isolate_local_index(tmp_path, monkeypatch):
    """每個測試使用獨立的臨時 SQLite DB"""
    # 重置 module-level singleton
    li._conn = None

    # 用 tmp_path 內的 DB 取代正式路徑
    tmp_db = str(tmp_path / "test_scan_index.db")
    monkeypatch.setattr(li, "_DB_PATH", tmp_db)

    # 避免 init_from_remote 觸發真實 DB 連線
    monkeypatch.setattr(li, "init_from_remote", lambda: None)

    yield tmp_db

    li.close()


# ============================================================================
# 基礎 CRUD
# ============================================================================


class TestIndexOperations:
    def test_add_and_check_index(self):
        li.add_index("daily_price", "2330")
        assert li.index_exists("daily_price", "2330") is True

    def test_not_exists_returns_false(self):
        assert li.index_exists("daily_price", "9999") is False

    def test_add_duplicate_is_safe(self):
        li.add_index("daily_price", "2330")
        li.add_index("daily_price", "2330")  # should not raise
        assert li.index_exists("daily_price", "2330") is True


class TestAllIndexed:
    def test_all_indexed_true(self):
        li.add_index("daily_price", "2330")
        li.add_index("chip_margin", "2330")
        assert li.all_indexed(["daily_price", "chip_margin"], "2330") is True

    def test_all_indexed_partial_false(self):
        li.add_index("daily_price", "2330")
        assert li.all_indexed(["daily_price", "chip_margin"], "2330") is False

    def test_all_indexed_empty_tables_false(self):
        assert li.all_indexed([], "2330") is False


# ============================================================================
# 失敗記錄
# ============================================================================


class TestFailureRecords:
    def test_add_and_check_failure(self):
        li.add_failure("daily_price", "2330", "timeout")
        assert li.failure_exists("daily_price", "2330") is True

    def test_failure_not_exists(self):
        assert li.failure_exists("daily_price", "9999") is False

    def test_clear_all_failures(self):
        li.add_failure("daily_price", "2330", "err1")
        li.add_failure("chip_margin", "2317", "err2")
        li.clear_failures()
        assert li.failure_exists("daily_price", "2330") is False
        assert li.failure_exists("chip_margin", "2317") is False

    def test_clear_specific_table(self):
        li.add_failure("daily_price", "2330", "err1")
        li.add_failure("chip_margin", "2317", "err2")
        li.clear_failures("daily_price")
        assert li.failure_exists("daily_price", "2330") is False
        assert li.failure_exists("chip_margin", "2317") is True

    def test_failure_summary(self):
        li.add_failure("daily_price", "2330", "err1")
        li.add_failure("daily_price", "2317", "err2")
        li.add_failure("chip_margin", "2330", "err3")
        summary = li.get_failure_summary()
        assert len(summary) == 2
        # sorted by count DESC
        assert summary[0] == ("daily_price", 2)
        assert summary[1] == ("chip_margin", 1)

    def test_add_failure_replaces_existing(self):
        li.add_failure("daily_price", "2330", "first error")
        li.add_failure("daily_price", "2330", "second error")
        # should not have two records
        conn = li._get_conn()
        count = conn.execute(
            "SELECT COUNT(*) FROM scan_failures WHERE stock_id='2330' AND table_name='daily_price'"
        ).fetchone()[0]
        assert count == 1


# ============================================================================
# 連線管理
# ============================================================================


class TestConnection:
    def test_close_and_reopen(self):
        li.add_index("daily_price", "2330")
        li.close()
        # Should transparently reopen
        assert li.index_exists("daily_price", "2330") is True

    def test_close_twice_is_safe(self):
        li.close()
        li.close()  # should not raise

    def test_tables_created_on_first_connect(self, isolate_local_index):
        conn = li._get_conn()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t[0] for t in tables}
        assert "scan_index" in table_names
        assert "scan_failures" in table_names
