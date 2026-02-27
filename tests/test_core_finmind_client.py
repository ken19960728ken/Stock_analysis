"""core/finmind_client.py 測試"""

from unittest.mock import MagicMock, patch

import pytest


class TestGetFmToken:
    def test_returns_token_from_env(self, monkeypatch):
        import core.finmind_client as fm
        fm._fm_token = None  # reset singleton
        monkeypatch.setenv("FINMIND_TOKEN", "test-jwt-123")
        token = fm.get_fm_token()
        assert token == "test-jwt-123"
        fm._fm_token = None  # cleanup

    def test_returns_none_when_no_env(self, monkeypatch):
        import core.finmind_client as fm
        fm._fm_token = None
        monkeypatch.delenv("FINMIND_TOKEN", raising=False)
        token = fm.get_fm_token()
        assert token is None
        fm._fm_token = None

    def test_caches_result(self, monkeypatch):
        import core.finmind_client as fm
        fm._fm_token = None
        monkeypatch.setenv("FINMIND_TOKEN", "cached-token")
        fm.get_fm_token()
        # Change env after first call — should still return cached value
        monkeypatch.setenv("FINMIND_TOKEN", "new-token")
        assert fm.get_fm_token() == "cached-token"
        fm._fm_token = None


class TestGetFmLoader:
    @patch("core.finmind_client.DataLoader")
    def test_returns_dataloader_instance(self, MockDL, monkeypatch):
        import core.finmind_client as fm
        fm._fm_loader = None
        fm._fm_token = None
        monkeypatch.delenv("FINMIND_TOKEN", raising=False)
        loader = fm.get_fm_loader()
        assert loader is not None
        MockDL.assert_called_once()
        fm._fm_loader = None
        fm._fm_token = None

    @patch("core.finmind_client.DataLoader")
    def test_with_token_calls_login(self, MockDL, monkeypatch):
        import core.finmind_client as fm
        fm._fm_loader = None
        fm._fm_token = None
        monkeypatch.setenv("FINMIND_TOKEN", "my-token")
        mock_instance = MagicMock()
        MockDL.return_value = mock_instance
        fm.get_fm_loader()
        mock_instance.login_by_token.assert_called_once_with(api_token="my-token")
        fm._fm_loader = None
        fm._fm_token = None

    @patch("core.finmind_client.DataLoader")
    def test_singleton_returns_same_instance(self, MockDL, monkeypatch):
        import core.finmind_client as fm
        fm._fm_loader = None
        fm._fm_token = None
        monkeypatch.delenv("FINMIND_TOKEN", raising=False)
        a = fm.get_fm_loader()
        b = fm.get_fm_loader()
        assert a is b
        MockDL.assert_called_once()
        fm._fm_loader = None
        fm._fm_token = None

    @patch("core.finmind_client.DataLoader")
    def test_login_failure_still_returns_loader(self, MockDL, monkeypatch):
        import core.finmind_client as fm
        fm._fm_loader = None
        fm._fm_token = None
        monkeypatch.setenv("FINMIND_TOKEN", "bad-token")
        mock_instance = MagicMock()
        mock_instance.login_by_token.side_effect = Exception("auth failed")
        MockDL.return_value = mock_instance
        loader = fm.get_fm_loader()
        assert loader is mock_instance  # still returns the loader
        fm._fm_loader = None
        fm._fm_token = None


class TestGetApiUsage:
    @patch("core.finmind_client.requests.get")
    def test_returns_usage_tuple(self, mock_get, monkeypatch):
        import core.finmind_client as fm
        fm._fm_token = None
        monkeypatch.setenv("FINMIND_TOKEN", "valid-token")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "user_count": 100,
            "api_request_limit": 500,
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        count, limit = fm.get_api_usage()
        assert count == 100
        assert limit == 500
        fm._fm_token = None

    def test_no_token_returns_none_tuple(self, monkeypatch):
        import core.finmind_client as fm
        fm._fm_token = None
        monkeypatch.delenv("FINMIND_TOKEN", raising=False)
        count, limit = fm.get_api_usage()
        assert count is None
        assert limit is None
        fm._fm_token = None

    @patch("core.finmind_client.requests.get", side_effect=Exception("network"))
    def test_api_error_returns_none_tuple(self, mock_get, monkeypatch):
        import core.finmind_client as fm
        fm._fm_token = None
        monkeypatch.setenv("FINMIND_TOKEN", "valid-token")
        count, limit = fm.get_api_usage()
        assert count is None
        assert limit is None
        fm._fm_token = None
