"""core/stock_list.py 測試"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from core.stock_list import FALLBACK_STOCKS, get_all_stocks, get_stock_ids_from_daily_price


class TestFallbackStocks:
    def test_is_list(self):
        assert isinstance(FALLBACK_STOCKS, list)

    def test_contains_tsmc(self):
        assert "2330" in FALLBACK_STOCKS

    def test_not_empty(self):
        assert len(FALLBACK_STOCKS) > 0


class TestGetAllStocks:
    @patch("core.stock_list.get_engine")
    @patch("core.stock_list.pd.read_sql")
    def test_returns_list_of_dicts(self, mock_read_sql, mock_engine):
        mock_read_sql.return_value = pd.DataFrame({
            "商品代號": ["2330", "6547"],
            "市場別": ["上市", "上櫃"],
            "商品名稱": ["台積電", "高端疫苗"],
            "商品類型": ["股票", "股票"],
        })
        result = get_all_stocks()
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["stock_id"] == "2330"
        assert result[0]["yahoo_symbol"] == "2330.TW"

    @patch("core.stock_list.get_engine")
    @patch("core.stock_list.pd.read_sql")
    def test_otc_gets_two_suffix(self, mock_read_sql, mock_engine):
        mock_read_sql.return_value = pd.DataFrame({
            "商品代號": ["6547"],
            "市場別": ["上櫃"],
            "商品名稱": ["高端疫苗"],
            "商品類型": ["股票"],
        })
        result = get_all_stocks()
        assert result[0]["yahoo_symbol"] == "6547.TWO"

    @patch("core.stock_list.get_engine")
    @patch("core.stock_list.pd.read_sql")
    def test_unknown_market_skipped(self, mock_read_sql, mock_engine):
        mock_read_sql.return_value = pd.DataFrame({
            "商品代號": ["1234"],
            "市場別": ["興櫃"],
            "商品名稱": ["興櫃公司"],
            "商品類型": ["股票"],
        })
        result = get_all_stocks()
        assert len(result) == 0

    @patch("core.stock_list.get_engine")
    @patch("core.stock_list.pd.read_sql", side_effect=Exception("DB error"))
    def test_db_error_returns_fallback(self, mock_read_sql, mock_engine):
        result = get_all_stocks()
        assert len(result) == len(FALLBACK_STOCKS)
        assert result[0]["stock_id"] == FALLBACK_STOCKS[0]

    @patch("core.stock_list.get_engine")
    @patch("core.stock_list.pd.read_sql")
    def test_fallback_has_correct_structure(self, mock_read_sql, mock_engine):
        mock_read_sql.side_effect = Exception("fail")
        result = get_all_stocks()
        for item in result:
            assert "stock_id" in item
            assert "yahoo_symbol" in item
            assert "name" in item
            assert "type" in item


class TestGetStockIdsFromDailyPrice:
    @patch("core.stock_list.get_engine")
    @patch("core.stock_list.pd.read_sql")
    def test_returns_list_of_ids(self, mock_read_sql, mock_engine):
        mock_read_sql.return_value = pd.DataFrame({
            "stock_id": ["2330", "2317", "2454"],
        })
        result = get_stock_ids_from_daily_price()
        assert result == ["2330", "2317", "2454"]

    @patch("core.stock_list.get_engine")
    @patch("core.stock_list.pd.read_sql")
    def test_empty_result_returns_fallback(self, mock_read_sql, mock_engine):
        mock_read_sql.return_value = pd.DataFrame({"stock_id": []})
        result = get_stock_ids_from_daily_price()
        assert result == FALLBACK_STOCKS

    @patch("core.stock_list.get_engine")
    @patch("core.stock_list.pd.read_sql", side_effect=Exception("DB error"))
    def test_exception_returns_fallback(self, mock_read_sql, mock_engine):
        result = get_stock_ids_from_daily_price()
        assert result == FALLBACK_STOCKS
