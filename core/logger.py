"""
統一日誌模組
- 正式環境：logs/scanner.log（RotatingFileHandler, 5MB x 3 備份）+ console
- 測試環境：由 conftest.py 配置獨立的 logs/test.log
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
LOG_FILE = os.path.join(LOG_DIR, "scanner.log")
LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

_initialized = False


def _ensure_log_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def _init_root_logger():
    """初始化 root logger（僅執行一次）"""
    global _initialized
    if _initialized:
        return
    _initialized = True

    _ensure_log_dir()

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT)

    # File handler: RotatingFileHandler 5MB x 3
    fh = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)
    root.addHandler(fh)

    # Console handler: 輸出到 stderr（與 tqdm 相容）
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)
    root.addHandler(ch)


def setup_logger(name: str) -> logging.Logger:
    """返回指定名稱的 logger，自動初始化 root handler"""
    _init_root_logger()
    return logging.getLogger(name)
