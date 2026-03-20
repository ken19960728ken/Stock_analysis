"""
種子資料腳本測試 — 報告解析 + 模擬資料生成

覆蓋：
  - Markdown 報告解析（regex 精確性）
  - 模擬資料生成（範圍檢查）
  - SQLite 寫入
"""

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from scripts.seed_recommendation_data import (
    parse_daily_pick_report,
    generate_simulated_records,
    create_local_db,
    _SCHEMA_SQL,
)


SAMPLE_REPORT = """# 每日選股報告 — 2026-03-17

## 報告摘要

- **策略組合**: RSI 反轉, 機器學習選股, 量價動能
- **掃描標的**: 2074 支
- **篩選結果**: 2 支推薦
- **最低門檻**: 至少 2 個策略給正分

## 推薦清單

### 1. 2399 映泰 — 總分 5.6 (2/11 策略同意)

| 指標 | 數值 |
|------|------|
| 收盤價 | 28.0 |
| 週漲跌幅 | +15.0% |
| 週量能變化 | +136.3% |
| RSI(14) | 64.6 |
| 20日均量 | 5875 張 |

**選股理由**:
- 機器學習選股: 近期評分 +5，03/17 觸發
- 量價動能: 近期評分 +3，03/17 觸發

### 2. 3583 辛耘 — 總分 4.9 (2/11 策略同意)

| 指標 | 數值 |
|------|------|
| 收盤價 | 408.0 |
| 週漲跌幅 | +9.8% |
| 週量能變化 | +67.5% |
| RSI(14) | 67.1 |
| 20日均量 | 2095 張 |

**選股理由**:
- 機器學習選股: 近期評分 +5，03/17 觸發
- 量價動能: 近期評分 +2，03/17 觸發

---

## 風險提示
"""


class TestParseReport:
    def test_parse_basic_report(self):
        records = parse_daily_pick_report(SAMPLE_REPORT, "2026-03-17")
        assert len(records) == 2
        assert records[0]["stock_id"] == "2399"
        assert records[0]["stock_name"] == "映泰"
        assert records[0]["rank"] == 1
        assert records[0]["total_score"] == 5.6
        assert records[0]["agree_count"] == 2
        assert records[0]["total_strategies"] == 11
        assert records[0]["entry_price"] == 28.0

    def test_parse_rsi(self):
        records = parse_daily_pick_report(SAMPLE_REPORT, "2026-03-17")
        assert records[0]["rsi"] == 64.6

    def test_parse_strategy_votes(self):
        records = parse_daily_pick_report(SAMPLE_REPORT, "2026-03-17")
        votes = records[0]["strategy_votes"]
        assert isinstance(votes, dict)
        assert "機器學習選股" in votes
        assert votes["機器學習選股"]["recent_score"] == 5.0

    def test_parse_empty_report(self):
        empty = "# 每日選股報告 — 2026-03-20\n\n## 無符合條件的股票\n"
        records = parse_daily_pick_report(empty, "2026-03-20")
        assert records == []


class TestGenerateSimulated:
    def test_generates_target_days(self):
        existing_dates = ["2026-03-10", "2026-03-11"]
        records = generate_simulated_records(
            existing_dates=existing_dates, target_days=5, stocks_per_day=3
        )
        unique_dates = set(r["report_date"] for r in records)
        assert len(unique_dates) == 3

    def test_return_range(self):
        records = generate_simulated_records(
            existing_dates=[], target_days=5, stocks_per_day=5
        )
        for r in records:
            if r.get("return_t5") is not None:
                assert -15.0 <= r["return_t5"] <= 15.0

    def test_is_simulated_flag(self):
        records = generate_simulated_records(
            existing_dates=[], target_days=3, stocks_per_day=2
        )
        assert all(r["is_simulated"] == 1 for r in records)


class TestCreateLocalDb:
    def test_creates_db_file(self, tmp_path):
        db_path = tmp_path / "test.db"
        create_local_db(db_path)
        assert db_path.exists()
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor]
        conn.close()
        assert "recommendation_history" in tables
