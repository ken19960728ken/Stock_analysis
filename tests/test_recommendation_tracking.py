"""
選股推薦追蹤機制測試 — 版本指紋 + 推薦儲存 + 績效回填

覆蓋：
  - 版本指紋收集（git SHA + app version + 策略 hash）
  - 推薦記錄 DB 寫入
  - 績效回填（交易日計算）
  - 績效追蹤報告產出
"""

import hashlib
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from scripts.daily_stock_picker import (
    collect_version_fingerprint,
    collect_strategy_hashes,
    save_recommendations,
    generate_report,
    STRATEGY_WEIGHTS,
)


class TestVersionFingerprint:
    """版本指紋收集"""

    @patch("scripts.daily_stock_picker.subprocess.check_output")
    def test_collect_version_fingerprint_returns_git_sha_and_version(self, mock_git):
        mock_git.return_value = b"a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2\n"
        result = collect_version_fingerprint()
        assert "git_commit" in result
        assert result["git_commit"] == "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
        assert "app_version" in result
        assert isinstance(result["app_version"], str)

    @patch("scripts.daily_stock_picker.subprocess.check_output")
    def test_collect_version_fingerprint_handles_git_failure(self, mock_git):
        mock_git.side_effect = Exception("not a git repo")
        result = collect_version_fingerprint()
        assert result["git_commit"] == "unknown"
        assert "app_version" in result

    def test_collect_strategy_hashes_returns_dict(self):
        result = collect_strategy_hashes()
        assert isinstance(result, dict)
        assert len(result) > 0
        # 應包含實際的策略檔案
        assert "rsi_reversal.py" in result
        assert "value_investing.py" in result
        # hash 應為 64 字元的 SHA256 hex
        for filename, hash_val in result.items():
            assert len(hash_val) == 64, f"{filename} hash 長度錯誤: {len(hash_val)}"

    def test_collect_strategy_hashes_excludes_non_strategy_files(self):
        result = collect_strategy_hashes()
        assert "__init__.py" not in result
        assert "base.py" not in result

    def test_collect_strategy_hashes_deterministic(self):
        """相同檔案應產出相同 hash"""
        result1 = collect_strategy_hashes()
        result2 = collect_strategy_hashes()
        assert result1 == result2


class TestSaveRecommendations:
    """推薦記錄寫入 DB"""

    @pytest.fixture
    def sample_scan_result(self):
        """模擬 scan_stocks() 的回傳結果"""
        return {
            "ranked": [
                {
                    "stock_id": "2330",
                    "total_score": 5.2,
                    "agree_count": 4,
                    "total_strategies": 11,
                    "last_close": 850.0,
                    "last_date": pd.Timestamp("2026-03-20"),
                    "week_return": 2.1,
                    "week_vol_change": 15.3,
                    "rsi": 55.2,
                    "avg_volume_20d": 25000.0,
                    "votes": {
                        "RSI 反轉": {"latest_signal": 1, "recent_score": 3.0, "signal_date": pd.Timestamp("2026-03-20")},
                        "價值投資": {"latest_signal": 0, "recent_score": 1.0, "signal_date": pd.Timestamp("2026-03-18")},
                    },
                },
                {
                    "stock_id": "2317",
                    "total_score": 3.8,
                    "agree_count": 3,
                    "total_strategies": 11,
                    "last_close": 120.0,
                    "last_date": pd.Timestamp("2026-03-20"),
                    "week_return": -1.5,
                    "week_vol_change": 5.0,
                    "rsi": 42.0,
                    "avg_volume_20d": 18000.0,
                    "votes": {
                        "RSI 反轉": {"latest_signal": 0, "recent_score": 0.0, "signal_date": None},
                        "法人跟單": {"latest_signal": 1, "recent_score": 2.0, "signal_date": pd.Timestamp("2026-03-19")},
                    },
                },
            ],
            "strategies_used": ["RSI 反轉", "價值投資", "法人跟單"],
            "total_scanned": 1800,
            "report_date": "2026-03-20",
            "ind_map": {
                "2330": {"sector": "半導體業", "sub_industry": "晶圓代工"},
                "2317": {"sector": "電腦及週邊設備業", "sub_industry": "筆電代工"},
            },
            "name_map": {"2330": "台積電", "2317": "鴻海"},
        }

    def test_build_recommendation_df(self, sample_scan_result):
        """測試建構推薦 DataFrame 的欄位完整性"""
        from scripts.daily_stock_picker import _build_recommendation_df
        df = _build_recommendation_df(sample_scan_result)
        assert len(df) == 2
        assert df.iloc[0]["stock_id"] == "2330"
        assert df.iloc[0]["rank"] == 1
        assert df.iloc[1]["rank"] == 2
        assert df.iloc[0]["entry_price"] == 850.0
        assert df.iloc[0]["sector"] == "半導體業"
        assert "git_commit" in df.columns
        assert "strategy_votes" in df.columns
        assert "strategy_hashes" in df.columns
        assert "strategy_weights" in df.columns
        assert "picker_config" in df.columns
        # JSONB 欄位應為 dict（pandas 寫入時自動轉 JSON）
        assert isinstance(df.iloc[0]["strategy_votes"], dict)
        assert isinstance(df.iloc[0]["strategy_hashes"], dict)

    @patch("scripts.daily_stock_picker.save_to_db")
    @patch("scripts.daily_stock_picker.collect_version_fingerprint")
    def test_save_recommendations_calls_save_to_db(self, mock_fp, mock_save, sample_scan_result):
        mock_fp.return_value = {"git_commit": "abc123", "app_version": "1.0.0"}
        mock_save.return_value = True
        result = save_recommendations(sample_scan_result)
        assert result is True
        mock_save.assert_called_once()
        call_args = mock_save.call_args
        saved_df = call_args[0][0]
        assert len(saved_df) == 2
        assert call_args[0][1] == "recommendation_history"

    @patch("scripts.daily_stock_picker.save_to_db")
    def test_save_recommendations_empty_ranked(self, mock_save):
        result = save_recommendations({"ranked": [], "report_date": "2026-03-20",
                                        "strategies_used": [], "ind_map": {}, "name_map": {}})
        assert result is False
        mock_save.assert_not_called()

    def test_votes_serialization_handles_timestamp(self, sample_scan_result):
        """signal_date 可能是 Timestamp，需正確序列化"""
        from scripts.daily_stock_picker import _build_recommendation_df
        df = _build_recommendation_df(sample_scan_result)
        votes = df.iloc[0]["strategy_votes"]
        # signal_date 應轉為 ISO 字串或 None
        for name, v in votes.items():
            if v["signal_date"] is not None:
                assert isinstance(v["signal_date"], str)


class TestReportVersionBlock:
    """報告版本指紋區塊"""

    @patch("scripts.daily_stock_picker.collect_version_fingerprint")
    @patch("scripts.daily_stock_picker.collect_strategy_hashes")
    def test_report_contains_version_block(self, mock_hashes, mock_fp):
        mock_fp.return_value = {"git_commit": "a1b2c3d4e5f6", "app_version": "1.0.0"}
        mock_hashes.return_value = {"rsi_reversal.py": "abc123"}
        report = generate_report(
            ranked=[],
            strategies_used=["RSI 反轉", "價值投資"],
            total_scanned=1800,
            report_date="2026-03-20",
        )
        assert "版本資訊" in report
        assert "a1b2c3d" in report
        assert "1.0.0" in report
