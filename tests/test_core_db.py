"""core/db.py 測試 — 白名單驗證、save_to_db、check_exists"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from core.db import (
    VALID_TABLES,
    _validate_table_name,
    check_exists,
    dispose_engine,
    save_to_db,
)


# ============================================================================
# 白名單驗證
# ============================================================================


class TestValidateTableName:
    def test_valid_table_passes(self):
        for t in ["daily_price", "chip_margin", "industry_mapping"]:
            assert _validate_table_name(t) == t

    def test_all_known_tables_pass(self):
        for t in VALID_TABLES:
            assert _validate_table_name(t) == t

    def test_invalid_table_raises(self):
        with pytest.raises(ValueError, match="非法資料表名稱"):
            _validate_table_name("drop_table_users")

    def test_sql_injection_attempt_raises(self):
        with pytest.raises(ValueError):
            _validate_table_name("daily_price; DROP TABLE users")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            _validate_table_name("")

    def test_valid_tables_is_frozenset(self):
        assert isinstance(VALID_TABLES, frozenset)

    def test_valid_tables_contains_key_tables(self):
        expected = {
            "daily_price", "weekly_price", "monthly_price",
            "financial_reports", "dividend_history",
            "chip_institutional", "chip_margin",
            "scan_progress", "industry_mapping",
        }
        assert expected.issubset(VALID_TABLES)


# ============================================================================
# save_to_db
# ============================================================================


class TestSaveToDb:
    @patch("core.db.get_engine")
    def test_empty_df_returns_false(self, mock_engine):
        assert save_to_db(pd.DataFrame(), "daily_price") is False

    @patch("core.db.get_engine")
    def test_none_returns_false(self, mock_engine):
        assert save_to_db(None, "daily_price") is False

    def test_invalid_table_raises(self):
        df = pd.DataFrame({"a": [1]})
        with pytest.raises(ValueError, match="非法資料表名稱"):
            save_to_db(df, "evil_table")

    @patch("core.db.get_engine")
    def test_valid_table_calls_to_sql(self, mock_engine):
        engine = MagicMock()
        mock_engine.return_value = engine
        df = pd.DataFrame({"a": [1, 2]})
        with patch.object(df, "to_sql") as mock_to_sql:
            result = save_to_db(df, "daily_price")
            mock_to_sql.assert_called_once()
            assert result is True

    @patch("core.db.get_engine")
    def test_to_sql_exception_returns_false(self, mock_engine):
        engine = MagicMock()
        mock_engine.return_value = engine
        df = pd.DataFrame({"a": [1]})
        with patch.object(df, "to_sql", side_effect=Exception("DB error")):
            result = save_to_db(df, "daily_price")
            assert result is False

    @patch("core.db.dispose_engine")
    @patch("core.db.get_engine")
    def test_connection_error_retries_once(self, mock_engine, mock_dispose):
        """SSL/connection error triggers dispose + retry"""
        engine = MagicMock()
        mock_engine.return_value = engine
        df = pd.DataFrame({"a": [1]})
        from sqlalchemy.exc import OperationalError
        ssl_err = OperationalError(
            "statement", {}, Exception("SSL connection has been closed unexpectedly")
        )
        with patch.object(df, "to_sql", side_effect=[ssl_err, None]):
            result = save_to_db(df, "daily_price")
            assert result is True
            mock_dispose.assert_called_once()

    @patch("core.db.dispose_engine")
    @patch("core.db.get_engine")
    def test_connection_error_retry_also_fails(self, mock_engine, mock_dispose):
        """Both attempts fail -> return False"""
        engine = MagicMock()
        mock_engine.return_value = engine
        df = pd.DataFrame({"a": [1]})
        from sqlalchemy.exc import OperationalError
        ssl_err = OperationalError(
            "statement", {}, Exception("SSL connection has been closed unexpectedly")
        )
        with patch.object(df, "to_sql", side_effect=[ssl_err, Exception("still broken")]):
            result = save_to_db(df, "daily_price")
            assert result is False
            mock_dispose.assert_called_once()


# ============================================================================
# check_exists
# ============================================================================


class TestCheckExists:
    def test_invalid_table_raises(self):
        with pytest.raises(ValueError, match="非法資料表名稱"):
            check_exists("evil_table", "2330")

    @patch("core.db.get_engine")
    def test_existing_stock_returns_true(self, mock_engine):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (1,)
        engine = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_engine.return_value = engine
        assert check_exists("daily_price", "2330") is True

    @patch("core.db.get_engine")
    def test_missing_stock_returns_false(self, mock_engine):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        engine = MagicMock()
        engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_engine.return_value = engine
        assert check_exists("daily_price", "9999") is False

    @patch("core.db.get_engine", side_effect=Exception("conn error"))
    def test_exception_returns_false(self, mock_engine):
        assert check_exists("daily_price", "2330") is False


# ============================================================================
# dispose_engine
# ============================================================================


class TestDisposeEngine:
    def test_dispose_resets_engine(self):
        import core.db as db_module
        original = db_module._engine
        db_module._engine = MagicMock()
        dispose_engine()
        assert db_module._engine is None
        db_module._engine = original

    def test_dispose_when_none_is_safe(self):
        import core.db as db_module
        original = db_module._engine
        db_module._engine = None
        dispose_engine()  # should not raise
        assert db_module._engine is None
        db_module._engine = original
