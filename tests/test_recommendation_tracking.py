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
