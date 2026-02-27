"""core/logger.py 測試"""

import logging
import os
from unittest.mock import patch

import pytest


class TestSetupLogger:
    def test_returns_logger_instance(self):
        import core.logger as lm
        logger = lm.setup_logger("test_module")
        assert isinstance(logger, logging.Logger)

    def test_returns_named_logger(self):
        import core.logger as lm
        logger = lm.setup_logger("my_test_name")
        assert logger.name == "my_test_name"

    def test_different_names_different_loggers(self):
        import core.logger as lm
        a = lm.setup_logger("aaa")
        b = lm.setup_logger("bbb")
        assert a is not b
        assert a.name != b.name

    def test_same_name_same_logger(self):
        import core.logger as lm
        a = lm.setup_logger("same_name")
        b = lm.setup_logger("same_name")
        assert a is b


class TestLogConstants:
    def test_log_format_contains_placeholders(self):
        from core.logger import LOG_FORMAT
        assert "%(levelname)s" in LOG_FORMAT
        assert "%(name)s" in LOG_FORMAT

    def test_log_datefmt(self):
        from core.logger import LOG_DATEFMT
        assert "%Y" in LOG_DATEFMT
        assert "%H" in LOG_DATEFMT

    def test_log_dir_exists(self):
        from core.logger import LOG_DIR
        assert isinstance(LOG_DIR, str)
        assert "logs" in LOG_DIR


class TestEnsureLogDir:
    def test_creates_log_dir(self, tmp_path):
        import core.logger as lm
        target = str(tmp_path / "new_logs")
        assert not os.path.exists(target)
        original = lm.LOG_DIR
        lm.LOG_DIR = target
        try:
            lm._ensure_log_dir()
            assert os.path.isdir(target)
        finally:
            lm.LOG_DIR = original

    def test_idempotent(self, tmp_path):
        import core.logger as lm
        target = str(tmp_path / "existing_logs")
        os.makedirs(target)
        original = lm.LOG_DIR
        lm.LOG_DIR = target
        try:
            lm._ensure_log_dir()  # should not raise
            assert os.path.isdir(target)
        finally:
            lm.LOG_DIR = original
