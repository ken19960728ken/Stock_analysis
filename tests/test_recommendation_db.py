"""
推薦追蹤資料層測試 — SQLite 讀取 + JSONB 轉換

覆蓋：
  - SQLite 讀寫
  - JSONB TEXT→dict 自動轉換
  - 日期範圍過濾
  - 空資料處理
  - 策略拆分展開
  - 版本時間軸
"""

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

# 測試前設定環境變數，強制使用 sqlite
os.environ["RECOMMENDATION_DB_SOURCE"] = "sqlite"

from analysis.utils.recommendation_db import (
    load_all_recommendations,
    load_recommendations_by_date,
    load_performance_summary,
    load_strategy_breakdown,
    load_version_timeline,
    load_open_positions,
    load_tracked_positions,
    _normalize_jsonb,
    _SQLITE_PATH,
)


@pytest.fixture
def tracked_db(tmp_path):
    """建立臨時 SQLite tracked_positions 並注入 open/closed 測試資料"""
    db_path = tmp_path / "tracked.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE tracked_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date DATE, stock_id TEXT, stock_name TEXT,
            entry_date DATE, entry_price FLOAT, status TEXT,
            current_price FLOAT, peak_price FLOAT, holding_days INT,
            unrealized_pnl_pct FLOAT, exit_date DATE, exit_price FLOAT,
            exit_reason TEXT, realized_pnl_pct FLOAT, exit_rule_config TEXT,
            total_score FLOAT, agree_count INT
        )
    """)
    cfg = json.dumps({"exit": "TimeStopExit(max_hold_days=20)"})
    conn.executemany(
        "INSERT INTO tracked_positions (report_date, stock_id, stock_name, "
        "entry_date, entry_price, status, current_price, peak_price, "
        "holding_days, unrealized_pnl_pct, exit_date, exit_price, exit_reason, "
        "realized_pnl_pct, exit_rule_config) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("2026-05-01", "2330", "台積電", "2026-05-01", 900.0, "open",
             950.0, 960.0, 10, 5.56, None, None, None, None, cfg),
            ("2026-05-03", "2317", "鴻海", "2026-05-03", 200.0, "closed",
             184.0, 205.0, 8, -8.0, "2026-05-14", 184.0, "stop_loss", -8.0, cfg),
        ],
    )
    conn.commit()
    conn.close()
    return db_path


class TestTrackedPositions:
    def test_load_all(self, tracked_db):
        with patch("analysis.utils.recommendation_db._SQLITE_PATH", tracked_db):
            df = load_tracked_positions()
        assert len(df) == 2

    def test_load_open_only(self, tracked_db):
        with patch("analysis.utils.recommendation_db._SQLITE_PATH", tracked_db):
            df = load_open_positions()
        assert len(df) == 1
        assert df.iloc[0]["stock_id"] == "2330"

    def test_exit_rule_config_normalized(self, tracked_db):
        with patch("analysis.utils.recommendation_db._SQLITE_PATH", tracked_db):
            df = load_tracked_positions()
        assert isinstance(df.iloc[0]["exit_rule_config"], dict)


@pytest.fixture
def sample_db(tmp_path):
    """建立臨時 SQLite DB 並注入測試資料"""
    db_path = tmp_path / "test_rec.db"

    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE recommendation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date DATE NOT NULL,
            stock_id VARCHAR(10) NOT NULL,
            stock_name VARCHAR(50),
            rank INT,
            total_score FLOAT,
            agree_count INT,
            total_strategies INT,
            entry_price FLOAT,
            rsi FLOAT,
            week_return FLOAT,
            avg_volume_20d FLOAT,
            sector VARCHAR(50),
            sub_industry VARCHAR(50),
            git_commit VARCHAR(40),
            app_version VARCHAR(20),
            strategy_votes TEXT,
            strategy_hashes TEXT,
            strategy_weights TEXT,
            picker_config TEXT,
            price_t5 FLOAT,
            price_t10 FLOAT,
            price_t20 FLOAT,
            return_t5 FLOAT,
            return_t10 FLOAT,
            return_t20 FLOAT,
            is_simulated BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(report_date, stock_id)
        )
    """)

    votes_a = json.dumps({"RSI 反轉": {"recent_score": 3.0, "signal_date": "2026-03-10"}})
    votes_b = json.dumps({"法人跟單": {"recent_score": 2.0, "signal_date": "2026-03-10"}})
    votes_c = json.dumps({"RSI 反轉": {"recent_score": 1.0, "signal_date": "2026-03-15"}})
    hashes = json.dumps({"rsi_reversal.py": "abc123"})
    weights = json.dumps({"RSI 反轉": 1.0, "法人跟單": 0.6})

    rows = [
        ("2026-03-10", "2330", "台積電", 1, 5.2, 4, 11, 850.0, 55.0, 2.1, 25000,
         "半導體業", None, "aaa1111", "1.0.0", votes_a, hashes, weights, "{}",
         860.0, 870.0, 880.0, 1.18, 2.35, 3.53, 0),
        ("2026-03-10", "2317", "鴻海", 2, 3.8, 3, 11, 120.0, 42.0, -1.5, 18000,
         "電腦及週邊設備業", None, "aaa1111", "1.0.0", votes_b, hashes, weights, "{}",
         118.0, 121.0, 125.0, -1.67, 0.83, 4.17, 0),
        ("2026-03-15", "2330", "台積電", 1, 4.5, 3, 11, 860.0, 52.0, 1.0, 24000,
         "半導體業", None, "bbb2222", "1.0.1", votes_c, hashes, weights, "{}",
         870.0, None, None, 1.16, None, None, 0),
    ]

    conn.executemany(
        "INSERT INTO recommendation_history "
        "(report_date, stock_id, stock_name, rank, total_score, agree_count, "
        "total_strategies, entry_price, rsi, week_return, avg_volume_20d, "
        "sector, sub_industry, git_commit, app_version, strategy_votes, "
        "strategy_hashes, strategy_weights, picker_config, "
        "price_t5, price_t10, price_t20, return_t5, return_t10, return_t20, is_simulated) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    return db_path


class TestNormalizeJsonb:
    def test_converts_text_to_dict(self):
        df = pd.DataFrame({"strategy_votes": ['{"a": 1}'], "other": ["x"]})
        result = _normalize_jsonb(df)
        assert isinstance(result.iloc[0]["strategy_votes"], dict)
        assert result.iloc[0]["other"] == "x"

    def test_skips_already_dict(self):
        df = pd.DataFrame({"strategy_votes": [{"a": 1}]})
        result = _normalize_jsonb(df)
        assert result.iloc[0]["strategy_votes"] == {"a": 1}

    def test_handles_none(self):
        df = pd.DataFrame({"strategy_votes": [None]})
        result = _normalize_jsonb(df)
        assert result.iloc[0]["strategy_votes"] is None

    def test_empty_df(self):
        df = pd.DataFrame()
        result = _normalize_jsonb(df)
        assert result.empty


class TestLoadAllRecommendations:
    def test_returns_all_rows(self, sample_db):
        with patch("analysis.utils.recommendation_db._SQLITE_PATH", sample_db):
            df = load_all_recommendations()
        assert len(df) == 3

    def test_jsonb_columns_are_dict(self, sample_db):
        with patch("analysis.utils.recommendation_db._SQLITE_PATH", sample_db):
            df = load_all_recommendations()
        assert isinstance(df.iloc[0]["strategy_votes"], dict)

    def test_empty_db(self, tmp_path):
        db_path = tmp_path / "empty.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""CREATE TABLE recommendation_history (
            id INTEGER PRIMARY KEY, report_date DATE, stock_id TEXT,
            strategy_votes TEXT, strategy_hashes TEXT,
            strategy_weights TEXT, picker_config TEXT
        )""")
        conn.close()
        with patch("analysis.utils.recommendation_db._SQLITE_PATH", db_path):
            df = load_all_recommendations()
        assert df.empty


class TestLoadByDate:
    def test_filter_by_date(self, sample_db):
        with patch("analysis.utils.recommendation_db._SQLITE_PATH", sample_db):
            df = load_recommendations_by_date("2026-03-14", "2026-03-20")
        assert len(df) == 1
        assert df.iloc[0]["stock_id"] == "2330"


class TestPerformanceSummary:
    def test_returns_summary(self, sample_db):
        with patch("analysis.utils.recommendation_db._SQLITE_PATH", sample_db):
            summary = load_performance_summary()
        assert "t5" in summary
        assert "avg_return" in summary["t5"]
        assert "win_rate" in summary["t5"]
        assert "sample_count" in summary["t5"]


class TestStrategyBreakdown:
    def test_returns_breakdown(self, sample_db):
        with patch("analysis.utils.recommendation_db._SQLITE_PATH", sample_db):
            df = load_strategy_breakdown()
        assert len(df) > 0
        assert "strategy" in df.columns
        assert "count" in df.columns
        assert "win_rate_t5" in df.columns


class TestVersionTimeline:
    def test_returns_versions(self, sample_db):
        with patch("analysis.utils.recommendation_db._SQLITE_PATH", sample_db):
            df = load_version_timeline()
        assert len(df) == 2  # 兩個不同 commit
        assert "git_commit" in df.columns
