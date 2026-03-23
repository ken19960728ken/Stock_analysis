"""core/db.py 測試 — 白名單驗證、save_to_db、JSONB 序列化、check_exists"""

import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from core.db import (
    VALID_TABLES,
    _auto_serialize_json_columns,
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

    @patch("core.db._save_chunk", return_value=True)
    def test_valid_table_calls_save_chunk(self, mock_chunk):
        df = pd.DataFrame({"a": [1, 2]})
        result = save_to_db(df, "daily_price")
        mock_chunk.assert_called_once()
        assert result is True

    @patch("core.db._save_chunk", side_effect=Exception("DB error"))
    def test_save_chunk_exception_propagates(self, mock_chunk):
        df = pd.DataFrame({"a": [1]})
        with pytest.raises(Exception, match="DB error"):
            save_to_db(df, "daily_price")

    @patch("core.db.dispose_engine")
    @patch("core.db.get_engine")
    def test_connection_error_retries_once(self, mock_engine, mock_dispose):
        """SSL/connection error triggers dispose + retry"""
        engine = MagicMock()
        mock_engine.return_value = engine
        from core.db import _save_chunk
        from sqlalchemy.exc import OperationalError
        ssl_err = OperationalError(
            "statement", {}, Exception("SSL connection has been closed unexpectedly")
        )
        df = pd.DataFrame({"a": [1]})
        with patch("pandas.DataFrame.to_sql", side_effect=[ssl_err, None]):
            result = _save_chunk(df, "daily_price", 500)
            assert result is True
            mock_dispose.assert_called_once()

    @patch("core.db.dispose_engine")
    @patch("core.db.get_engine")
    def test_connection_error_retry_also_fails(self, mock_engine, mock_dispose):
        """Both attempts fail -> return False"""
        engine = MagicMock()
        mock_engine.return_value = engine
        from core.db import _save_chunk
        from sqlalchemy.exc import OperationalError
        ssl_err = OperationalError(
            "statement", {}, Exception("SSL connection has been closed unexpectedly")
        )
        df = pd.DataFrame({"a": [1]})
        with patch("pandas.DataFrame.to_sql", side_effect=[ssl_err, Exception("still broken")]):
            result = _save_chunk(df, "daily_price", 500)
            assert result is False
            mock_dispose.assert_called_once()


# ============================================================================
# _auto_serialize_json_columns（JSONB 寫入防護）
# ============================================================================


class TestAutoSerializeJsonColumns:
    """確保 dict/list → JSON 字串，防止 psycopg2 'can't adapt type dict' 錯誤"""

    def test_dict_column_becomes_json_string(self):
        df = pd.DataFrame([{"name": "2330", "data": {"key": "val"}}])
        result = _auto_serialize_json_columns(df)
        assert isinstance(result.iloc[0]["data"], str)
        assert json.loads(result.iloc[0]["data"]) == {"key": "val"}

    def test_list_column_becomes_json_string(self):
        df = pd.DataFrame([{"tags": ["a", "b"]}])
        result = _auto_serialize_json_columns(df)
        assert isinstance(result.iloc[0]["tags"], str)
        assert json.loads(result.iloc[0]["tags"]) == ["a", "b"]

    def test_plain_columns_unchanged(self):
        df = pd.DataFrame([{"name": "TSMC", "price": 850.0, "rank": 1}])
        result = _auto_serialize_json_columns(df)
        assert result.iloc[0]["name"] == "TSMC"
        assert result.iloc[0]["price"] == 850.0
        assert result.iloc[0]["rank"] == 1

    def test_none_in_dict_column_stays_none(self):
        df = pd.DataFrame([
            {"data": {"k": "v"}},
            {"data": None},
        ])
        result = _auto_serialize_json_columns(df)
        assert isinstance(result.iloc[0]["data"], str)
        assert result.iloc[1]["data"] is None

    def test_does_not_mutate_original(self):
        df = pd.DataFrame([{"data": {"k": "v"}}])
        _auto_serialize_json_columns(df)
        assert isinstance(df.iloc[0]["data"], dict), "原始 DataFrame 不應被修改"

    def test_nested_dict_with_chinese(self):
        """中文內容 + 巢狀結構應正確序列化"""
        df = pd.DataFrame([{"votes": {"RSI 反轉": {"score": 1.0, "日期": "2026-03-20"}}}])
        result = _auto_serialize_json_columns(df)
        parsed = json.loads(result.iloc[0]["votes"])
        assert parsed["RSI 反轉"]["日期"] == "2026-03-20"

    @patch("core.db.get_engine")
    def test_save_to_db_auto_serializes_dict(self, mock_engine):
        """save_to_db 整合路徑：dict 欄位應在寫入前被序列化"""
        engine = MagicMock()
        mock_engine.return_value = engine

        df = pd.DataFrame([{
            "report_date": "2026-03-23",
            "stock_id": "2330",
            "strategy_votes": {"RSI 反轉": {"score": 1.0}},
            "picker_config": {"top_n": 20},
        }])
        # 攔截 to_sql 呼叫，檢查傳入的 DataFrame
        captured_df = {}

        def fake_to_sql(name, eng, **kwargs):
            captured_df["df"] = df  # to_sql 被呼叫時 df 已是序列化後的版本

        with patch("pandas.DataFrame.to_sql", side_effect=fake_to_sql):
            save_to_db(df, "recommendation_history")

        # 驗證 save_to_db 內部不會因為 dict 欄位而拋出異常
        # （如果沒有 _auto_serialize_json_columns，psycopg2 會報錯）


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
