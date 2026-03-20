# 推薦命中率儀表板 — 實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 建立 Streamlit 頁面展示選股推薦的歷史績效，含整體勝率、策略拆分、排名 vs 績效、時間趨勢四個區塊。

**Architecture:** 資料層 `recommendation_db.py` 封裝 SQLite/Supabase 切換（環境變數控制），種子腳本從現有報告 + Supabase 價格資料建立本地 SQLite，Streamlit 頁面只呼叫資料層。

**Tech Stack:** Python 3.11, pandas, SQLAlchemy, sqlite3, Streamlit, Plotly, scipy (linregress)

**設計文件:** `docs/plans/2026-03-20-recommendation-dashboard-design.md`

---

### Task 1: 資料層 — recommendation_db.py（TDD）

**Files:**
- Create: `analysis/utils/recommendation_db.py`
- Create: `tests/test_recommendation_db.py`

**Step 1: 寫測試**

建立 `tests/test_recommendation_db.py`：

```python
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
    _normalize_jsonb,
    _SQLITE_PATH,
)


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
    """JSONB TEXT→dict 轉換"""

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
    """全量讀取"""

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
    """日期範圍過濾"""

    def test_filter_by_date(self, sample_db):
        with patch("analysis.utils.recommendation_db._SQLITE_PATH", sample_db):
            df = load_recommendations_by_date("2026-03-14", "2026-03-20")
        assert len(df) == 1
        assert df.iloc[0]["stock_id"] == "2330"


class TestPerformanceSummary:
    """績效摘要"""

    def test_returns_summary(self, sample_db):
        with patch("analysis.utils.recommendation_db._SQLITE_PATH", sample_db):
            summary = load_performance_summary()
        assert "t5" in summary
        assert "avg_return" in summary["t5"]
        assert "win_rate" in summary["t5"]
        assert "sample_count" in summary["t5"]


class TestStrategyBreakdown:
    """策略拆分"""

    def test_returns_breakdown(self, sample_db):
        with patch("analysis.utils.recommendation_db._SQLITE_PATH", sample_db):
            df = load_strategy_breakdown()
        assert len(df) > 0
        assert "strategy" in df.columns
        assert "count" in df.columns
        assert "win_rate_t5" in df.columns


class TestVersionTimeline:
    """版本時間軸"""

    def test_returns_versions(self, sample_db):
        with patch("analysis.utils.recommendation_db._SQLITE_PATH", sample_db):
            df = load_version_timeline()
        assert len(df) == 2  # 兩個不同 commit
        assert "git_commit" in df.columns
```

**Step 2: 跑測試確認失敗**

```bash
uv run pytest tests/test_recommendation_db.py -v
```

預期：ImportError（模組尚未存在）

**Step 3: 實作 analysis/utils/recommendation_db.py**

```python
"""
推薦追蹤資料層 — 封裝 SQLite / Supabase 切換

⚠️ 開發模式：預設讀取本地 SQLite（data/recommendation_local.db）
   正式環境：設環境變數 RECOMMENDATION_DB_SOURCE=supabase 切換到 Supabase
"""

import json
import os
import sqlite3
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_DATA_SOURCE = os.getenv("RECOMMENDATION_DB_SOURCE", "sqlite")
_SQLITE_PATH = PROJECT_ROOT / "data" / "recommendation_local.db"

_JSONB_COLUMNS = ["strategy_votes", "strategy_hashes", "strategy_weights", "picker_config"]


def _normalize_jsonb(df: pd.DataFrame) -> pd.DataFrame:
    """SQLite 讀出的 JSONB 欄位為 TEXT，轉為 dict"""
    for col in _JSONB_COLUMNS:
        if col in df.columns:
            df[col] = df[col].apply(
                lambda x: json.loads(x) if isinstance(x, str) else x
            )
    return df


def _read_sql(sql: str, params: dict | None = None) -> pd.DataFrame:
    """根據 _DATA_SOURCE 選擇讀取方式"""
    if _DATA_SOURCE == "supabase":
        from core.db import safe_read_sql
        return safe_read_sql(sql, params=params)

    # SQLite 模式
    if not _SQLITE_PATH.exists():
        return pd.DataFrame()

    conn = sqlite3.connect(str(_SQLITE_PATH))
    try:
        if params:
            # 將 %(key)s 格式轉為 :key 格式（SQLite 用 :key）
            for key in params:
                sql = sql.replace(f"%({key})s", f":{key}")
        df = pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()
    return _normalize_jsonb(df)


def load_all_recommendations() -> pd.DataFrame:
    """全量推薦記錄"""
    df = _read_sql(
        "SELECT * FROM recommendation_history ORDER BY report_date DESC, rank"
    )
    return df


def load_recommendations_by_date(start: str, end: str) -> pd.DataFrame:
    """日期範圍過濾"""
    df = _read_sql(
        "SELECT * FROM recommendation_history "
        "WHERE report_date >= %(start)s AND report_date <= %(end)s "
        "ORDER BY report_date DESC, rank",
        params={"start": start, "end": end},
    )
    return df


def load_performance_summary() -> dict:
    """
    整體績效摘要。

    Returns
    -------
    dict : {"t5": {"avg_return": float, "win_rate": float, "sample_count": int}, "t10": ..., "t20": ...}
    """
    df = _read_sql("SELECT return_t5, return_t10, return_t20 FROM recommendation_history")
    if df.empty:
        empty = {"avg_return": 0.0, "win_rate": 0.0, "sample_count": 0}
        return {"t5": dict(empty), "t10": dict(empty), "t20": dict(empty)}

    summary = {}
    for t in ["t5", "t10", "t20"]:
        col = f"return_{t}"
        valid = df[col].dropna()
        if valid.empty:
            summary[t] = {"avg_return": 0.0, "win_rate": 0.0, "sample_count": 0}
        else:
            summary[t] = {
                "avg_return": round(float(valid.mean()), 2),
                "win_rate": round(float((valid > 0).mean() * 100), 1),
                "sample_count": int(valid.count()),
            }
    return summary


def load_strategy_breakdown() -> pd.DataFrame:
    """
    展開 strategy_votes → 每策略推薦次數 + T+5 勝率 + T+5 平均報酬。

    Returns
    -------
    DataFrame : columns = [strategy, count, win_rate_t5, avg_return_t5]
    """
    df = _read_sql(
        "SELECT strategy_votes, return_t5 FROM recommendation_history "
        "WHERE return_t5 IS NOT NULL"
    )
    if df.empty:
        return pd.DataFrame(columns=["strategy", "count", "win_rate_t5", "avg_return_t5"])

    records: dict[str, list[float]] = {}
    for _, row in df.iterrows():
        votes = row["strategy_votes"]
        if not isinstance(votes, dict):
            continue
        for name, v in votes.items():
            if isinstance(v, dict) and v.get("recent_score", 0) > 0:
                records.setdefault(name, []).append(row["return_t5"])

    rows = []
    for name, returns in sorted(records.items(), key=lambda x: -len(x[1])):
        count = len(returns)
        win_rate = round(sum(1 for r in returns if r > 0) / count * 100, 1) if count else 0.0
        avg_ret = round(sum(returns) / count, 2) if count else 0.0
        rows.append({"strategy": name, "count": count, "win_rate_t5": win_rate, "avg_return_t5": avg_ret})

    return pd.DataFrame(rows)


def load_version_timeline() -> pd.DataFrame:
    """
    git_commit + app_version 的日期序列（版本變更點）。

    Returns
    -------
    DataFrame : columns = [report_date, git_commit, app_version]，只包含版本變更的日期
    """
    df = _read_sql(
        "SELECT report_date, git_commit, app_version FROM recommendation_history "
        "ORDER BY report_date"
    )
    if df.empty:
        return pd.DataFrame(columns=["report_date", "git_commit", "app_version"])

    daily = df.groupby("report_date").agg({"git_commit": "first", "app_version": "first"}).reset_index()
    daily = daily.sort_values("report_date")

    # 只保留版本變更的日期
    changes = [daily.iloc[0]]
    for i in range(1, len(daily)):
        if daily.iloc[i]["git_commit"] != daily.iloc[i - 1]["git_commit"]:
            changes.append(daily.iloc[i])

    return pd.DataFrame(changes).reset_index(drop=True)
```

**Step 4: 跑測試確認通過**

```bash
uv run pytest tests/test_recommendation_db.py -v
```

預期：全部 PASSED

**Step 5: Commit**

```bash
git add analysis/utils/recommendation_db.py tests/test_recommendation_db.py
git commit -m "feat: 新增推薦追蹤資料層 — SQLite/Supabase 切換 + JSONB 轉換"
```

---

### Task 2: 種子資料腳本（TDD）

**Files:**
- Create: `scripts/seed_recommendation_data.py`
- Create: `tests/test_seed_recommendation.py`

**Step 1: 寫測試**

建立 `tests/test_seed_recommendation.py`：

```python
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
    """報告解析"""

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
    """模擬資料生成"""

    def test_generates_target_days(self):
        existing_dates = ["2026-03-10", "2026-03-11"]
        records = generate_simulated_records(
            existing_dates=existing_dates, target_days=5, stocks_per_day=3
        )
        # 應生成 5 - 2 = 3 天的資料
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
    """SQLite 建立"""

    def test_creates_db_file(self, tmp_path):
        db_path = tmp_path / "test.db"
        create_local_db(db_path)
        assert db_path.exists()
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor]
        conn.close()
        assert "recommendation_history" in tables
```

**Step 2: 跑測試確認失敗**

```bash
uv run pytest tests/test_seed_recommendation.py -v
```

預期：ImportError

**Step 3: 實作 scripts/seed_recommendation_data.py**

```python
"""
種子資料腳本 — 建立本地 SQLite 推薦追蹤資料庫

⚠️ 開發用：本地 SQLite 資料，後續切換 RECOMMENDATION_DB_SOURCE=supabase 使用真實資料

三層策略（優先順序）：
1. 從 Supabase recommendation_history dump（如有資料）
2. 從 reports/daily_pick_*.md 解析 + Supabase daily_price 查後續價格
3. 純模擬資料（--mock-only，不需外部連線）

用法:
    uv run python scripts/seed_recommendation_data.py              # 自動選最佳來源 + 補模擬到 30 天
    uv run python scripts/seed_recommendation_data.py --real-only  # 只用真實資料
    uv run python scripts/seed_recommendation_data.py --mock-only  # 純模擬
    uv run python scripts/seed_recommendation_data.py --days 60    # 補模擬到 60 天
"""

import argparse
import json
import os
import random
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.logger import setup_logger

logger = setup_logger("seed_recommendation")

_SQLITE_PATH = PROJECT_ROOT / "data" / "recommendation_local.db"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS recommendation_history (
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
"""


# ===================================================================
# SQLite 操作
# ===================================================================

def create_local_db(db_path: Path | None = None) -> Path:
    """建立本地 SQLite DB（含 schema）"""
    if db_path is None:
        db_path = _SQLITE_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(_SCHEMA_SQL)
    conn.commit()
    conn.close()
    logger.info(f"SQLite DB 已建立: {db_path}")
    return db_path


def _insert_records(records: list[dict], db_path: Path | None = None):
    """批量寫入推薦記錄到 SQLite"""
    if not records:
        return
    if db_path is None:
        db_path = _SQLITE_PATH

    conn = sqlite3.connect(str(db_path))
    for r in records:
        # JSONB 欄位轉 TEXT
        for col in ["strategy_votes", "strategy_hashes", "strategy_weights", "picker_config"]:
            if col in r and isinstance(r[col], dict):
                r[col] = json.dumps(r[col], ensure_ascii=False)

        cols = list(r.keys())
        placeholders = ", ".join("?" for _ in cols)
        col_str = ", ".join(cols)
        vals = [r[c] for c in cols]
        try:
            conn.execute(
                f"INSERT OR IGNORE INTO recommendation_history ({col_str}) VALUES ({placeholders})",
                vals,
            )
        except Exception as e:
            logger.warning(f"寫入失敗 {r.get('stock_id')}: {e}")
    conn.commit()
    conn.close()


# ===================================================================
# 報告解析
# ===================================================================

# 標題格式: ### 1. 2399 映泰 — 總分 5.6 (2/11 策略同意)
_RE_STOCK_HEADER = re.compile(
    r"^### (\d+)\. (\d{4,6})\s+(.+?)\s+—\s+總分\s+([\d.]+)\s+\((\d+)/(\d+)\s+策略同意\)"
)
# 收盤價: | 收盤價 | 28.0 |
_RE_CLOSE = re.compile(r"\|\s*收盤價\s*\|\s*([\d.]+)")
# RSI: | RSI(14) | 64.6 |
_RE_RSI = re.compile(r"\|\s*RSI\(14\)\s*\|\s*([\d.]+)")
# 週漲跌幅: | 週漲跌幅 | +15.0% |
_RE_WEEK_RETURN = re.compile(r"\|\s*週漲跌幅\s*\|\s*([+-]?[\d.]+)%")
# 20日均量: | 20日均量 | 5875 張 |
_RE_AVG_VOL = re.compile(r"\|\s*20日均量\s*\|\s*([\d.]+)\s*張")
# 選股理由: - 機器學習選股: 近期評分 +5，03/17 觸發
_RE_VOTE = re.compile(r"^- (.+?):\s*近期評分\s*\+(\d+)(?:，(\d{2}/\d{2})\s*觸發)?")


def parse_daily_pick_report(content: str, report_date: str) -> list[dict]:
    """
    解析每日選股報告 Markdown，回傳推薦記錄列表。

    Parameters
    ----------
    content : str
        報告 Markdown 內容
    report_date : str
        報告日期（YYYY-MM-DD）

    Returns
    -------
    list[dict] : 推薦記錄（可直接寫入 SQLite）
    """
    records = []
    current: dict | None = None

    for line in content.split("\n"):
        # 嘗試匹配股票標題
        m = _RE_STOCK_HEADER.match(line)
        if m:
            if current is not None:
                records.append(current)
            current = {
                "report_date": report_date,
                "rank": int(m.group(1)),
                "stock_id": m.group(2),
                "stock_name": m.group(3).strip(),
                "total_score": float(m.group(4)),
                "agree_count": int(m.group(5)),
                "total_strategies": int(m.group(6)),
                "entry_price": None,
                "rsi": None,
                "week_return": None,
                "avg_volume_20d": None,
                "strategy_votes": {},
                "is_simulated": 0,
            }
            continue

        if current is None:
            continue

        # 解析指標
        m = _RE_CLOSE.search(line)
        if m:
            current["entry_price"] = float(m.group(1))
            continue

        m = _RE_RSI.search(line)
        if m:
            current["rsi"] = float(m.group(1))
            continue

        m = _RE_WEEK_RETURN.search(line)
        if m:
            current["week_return"] = float(m.group(1))
            continue

        m = _RE_AVG_VOL.search(line)
        if m:
            current["avg_volume_20d"] = float(m.group(1))
            continue

        # 解析選股理由
        m = _RE_VOTE.match(line.strip())
        if m:
            strategy_name = m.group(1)
            score = float(m.group(2))
            signal_date = None
            if m.group(3):
                year = report_date[:4]
                signal_date = f"{year}-{m.group(3).replace('/', '-')}"
            current["strategy_votes"][strategy_name] = {
                "recent_score": score,
                "signal_date": signal_date,
            }

    if current is not None:
        records.append(current)

    return records


# ===================================================================
# 後續價格查詢（從 Supabase）
# ===================================================================

def _backfill_prices(records: list[dict]) -> list[dict]:
    """從 Supabase daily_price 查 T+5/T+10/T+20 後續價格（唯讀）"""
    try:
        from core.db import safe_read_sql
    except Exception:
        logger.warning("無法連線 Supabase，跳過價格回填")
        return records

    for r in records:
        sid = r["stock_id"]
        rd = r["report_date"]
        try:
            prices = safe_read_sql(
                "SELECT date, close FROM daily_price "
                "WHERE stock_id = %(sid)s AND date > %(rd)s "
                "ORDER BY date LIMIT 25",
                params={"sid": sid, "rd": rd},
            )
        except Exception:
            continue

        if prices.empty:
            continue

        n = len(prices)
        if n >= 5:
            p5 = float(prices.iloc[4]["close"])
            r["price_t5"] = p5
            r["return_t5"] = round((p5 / r["entry_price"] - 1) * 100, 2) if r["entry_price"] else None
        if n >= 10:
            p10 = float(prices.iloc[9]["close"])
            r["price_t10"] = p10
            r["return_t10"] = round((p10 / r["entry_price"] - 1) * 100, 2) if r["entry_price"] else None
        if n >= 20:
            p20 = float(prices.iloc[19]["close"])
            r["price_t20"] = p20
            r["return_t20"] = round((p20 / r["entry_price"] - 1) * 100, 2) if r["entry_price"] else None

    return records


# ===================================================================
# 模擬資料生成
# ===================================================================

# 模擬用的股票池
_MOCK_STOCKS = [
    ("2330", "台積電"), ("2317", "鴻海"), ("2454", "聯發科"), ("2308", "台達電"),
    ("2882", "國泰金"), ("2881", "富邦金"), ("2303", "聯電"), ("3711", "日月光投控"),
    ("2412", "中華電"), ("1301", "台塑"), ("2002", "中鋼"), ("3034", "聯詠"),
    ("2886", "兆豐金"), ("2891", "中信金"), ("5880", "合庫金"),
]

_MOCK_STRATEGIES = ["RSI 反轉", "價值投資", "機器學習選股", "法人跟單", "量價動能", "營收動能"]


def generate_simulated_records(
    existing_dates: list[str],
    target_days: int = 30,
    stocks_per_day: int = 15,
) -> list[dict]:
    """
    生成模擬推薦記錄（標記 is_simulated=1）。

    Parameters
    ----------
    existing_dates : list[str]
        已有真實資料的日期列表
    target_days : int
        總共需要幾天的資料
    stocks_per_day : int
        每天推薦幾支

    Returns
    -------
    list[dict] : 模擬推薦記錄
    """
    existing_set = set(existing_dates)
    need_days = target_days - len(existing_set)
    if need_days <= 0:
        return []

    # 生成交易日序列（往前推）
    base_date = datetime(2026, 3, 17)
    all_dates = []
    d = base_date
    while len(all_dates) < target_days + 10:
        if d.weekday() < 5:  # 排除週末
            ds = d.strftime("%Y-%m-%d")
            if ds not in existing_set:
                all_dates.append(ds)
        d -= timedelta(days=1)

    sim_dates = all_dates[:need_days]
    random.seed(42)

    records = []
    for date_str in sim_dates:
        stocks = random.sample(_MOCK_STOCKS, min(stocks_per_day, len(_MOCK_STOCKS)))
        for rank, (sid, name) in enumerate(stocks, 1):
            entry_price = random.uniform(15, 900)
            # 報酬率：N(0.5%, 3%)，限制在 [-15%, +15%]
            ret_t5 = max(-15.0, min(15.0, round(random.gauss(0.5, 3.0), 2)))
            ret_t10 = max(-15.0, min(15.0, round(random.gauss(0.8, 4.0), 2)))
            ret_t20 = max(-15.0, min(15.0, round(random.gauss(1.0, 5.0), 2)))

            # 隨機選 2-4 個策略
            n_strats = random.randint(2, 4)
            chosen = random.sample(_MOCK_STRATEGIES, n_strats)
            votes = {}
            for s in chosen:
                votes[s] = {
                    "recent_score": float(random.randint(1, 5)),
                    "signal_date": date_str,
                }

            records.append({
                "report_date": date_str,
                "stock_id": sid,
                "stock_name": name,
                "rank": rank,
                "total_score": round(random.uniform(2.0, 8.0), 1),
                "agree_count": n_strats,
                "total_strategies": 11,
                "entry_price": round(entry_price, 1),
                "rsi": round(random.uniform(30, 70), 1),
                "week_return": round(random.uniform(-5, 10), 1),
                "avg_volume_20d": round(random.uniform(500, 30000), 0),
                "git_commit": "simulated",
                "app_version": "1.0.0",
                "strategy_votes": votes,
                "strategy_hashes": {},
                "strategy_weights": {},
                "picker_config": {},
                "price_t5": round(entry_price * (1 + ret_t5 / 100), 1),
                "price_t10": round(entry_price * (1 + ret_t10 / 100), 1),
                "price_t20": round(entry_price * (1 + ret_t20 / 100), 1),
                "return_t5": ret_t5,
                "return_t10": ret_t10,
                "return_t20": ret_t20,
                "is_simulated": 1,
            })

    return records


# ===================================================================
# 主流程
# ===================================================================

def _try_dump_supabase() -> list[dict]:
    """嘗試從 Supabase recommendation_history dump 全量資料"""
    try:
        from core.db import safe_read_sql
        df = safe_read_sql("SELECT * FROM recommendation_history ORDER BY report_date, rank")
        if df.empty:
            return []
        logger.info(f"從 Supabase dump {len(df)} 筆推薦記錄")
        return df.to_dict("records")
    except Exception as e:
        logger.info(f"Supabase 不可用或無資料: {e}")
        return []


def _parse_all_reports() -> list[dict]:
    """解析所有 daily_pick 報告"""
    report_dir = PROJECT_ROOT / "reports"
    records = []
    for f in sorted(report_dir.glob("daily_pick_*.md")):
        date_str = f.stem.replace("daily_pick_", "")
        content = f.read_text(encoding="utf-8")
        parsed = parse_daily_pick_report(content, date_str)
        records.extend(parsed)
        logger.info(f"解析 {f.name}: {len(parsed)} 筆")

    if records:
        records = _backfill_prices(records)

    return records


def run_seed(target_days: int = 30, real_only: bool = False, mock_only: bool = False):
    """執行種子資料建立"""
    db_path = create_local_db()

    if mock_only:
        logger.info("純模擬模式")
        records = generate_simulated_records([], target_days=target_days)
        _insert_records(records, db_path)
        logger.info(f"寫入 {len(records)} 筆模擬記錄")
        return

    # 策略 1: Supabase dump
    records = _try_dump_supabase()

    # 策略 2: 報告解析
    if not records:
        records = _parse_all_reports()

    if records:
        _insert_records(records, db_path)
        logger.info(f"寫入 {len(records)} 筆真實記錄")

    # 補模擬資料
    if not real_only:
        existing_dates = list(set(r["report_date"] for r in records))
        sim_records = generate_simulated_records(existing_dates, target_days=target_days)
        if sim_records:
            _insert_records(sim_records, db_path)
            logger.info(f"補充 {len(sim_records)} 筆模擬記錄")


def main():
    parser = argparse.ArgumentParser(description="建立本地推薦追蹤 SQLite")
    parser.add_argument("--days", type=int, default=30, help="目標天數（預設 30）")
    parser.add_argument("--real-only", action="store_true", help="只用真實資料")
    parser.add_argument("--mock-only", action="store_true", help="純模擬（不需外部連線）")
    args = parser.parse_args()
    run_seed(target_days=args.days, real_only=args.real_only, mock_only=args.mock_only)


if __name__ == "__main__":
    main()
```

**Step 4: 跑測試確認通過**

```bash
uv run pytest tests/test_seed_recommendation.py -v
```

預期：全部 PASSED

**Step 5: Commit**

```bash
git add scripts/seed_recommendation_data.py tests/test_seed_recommendation.py
git commit -m "feat: 新增種子資料腳本 — 報告解析 + 模擬資料 + SQLite 寫入"
```

---

### Task 3: 執行種子資料建立

**Step 1: 執行 seed 腳本**

```bash
uv run python scripts/seed_recommendation_data.py
```

預期輸出：
- 「從 Supabase dump N 筆推薦記錄」或「解析 daily_pick_*.md: N 筆」
- 「補充 M 筆模擬記錄」
- 產出 `data/recommendation_local.db`

**Step 2: 驗證 SQLite 內容**

```bash
uv run python -c "
import sqlite3
conn = sqlite3.connect('data/recommendation_local.db')
cur = conn.execute('SELECT COUNT(*), COUNT(DISTINCT report_date), SUM(is_simulated) FROM recommendation_history')
total, dates, simulated = cur.fetchone()
print(f'總記錄: {total}, 日期數: {dates}, 模擬: {simulated}, 真實: {total - (simulated or 0)}')
conn.close()
"
```

**Step 3: Commit**（如果 seed 腳本有微調）

```bash
git add -u
git commit -m "fix: seed 腳本微調（如有）"
```

---

### Task 4: 儀表板頁面 — 13_推薦追蹤.py

**Files:**
- Create: `analysis/pages/13_推薦追蹤.py`

**Step 1: 建立頁面**

```python
"""
推薦命中率儀表板 — 追蹤每日選股報告的歷史績效

⚠️ 開發模式：目前讀取本地 SQLite（data/recommendation_local.db）
   正式環境：設環境變數 RECOMMENDATION_DB_SOURCE=supabase 切換到真實資料

區塊：
  1. 整體績效概覽（metrics + 報酬分佈直方圖）
  2. 策略拆分命中率（表格 + 長條圖）
  3. 排名 vs 績效（散點圖 + 分組對比）
  4. 時間趨勢（折線圖 + 版本變更標記）
"""

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis.utils.recommendation_db import (
    load_all_recommendations,
    load_recommendations_by_date,
    load_performance_summary,
    load_strategy_breakdown,
    load_version_timeline,
)

st.set_page_config(page_title="推薦追蹤", page_icon="🎯", layout="wide")
st.title("推薦命中率儀表板")

data_source = os.getenv("RECOMMENDATION_DB_SOURCE", "sqlite")
if data_source == "sqlite":
    st.caption("⚠️ 開發模式 — 使用本地 SQLite 資料（含模擬資料）。正式環境請設 `RECOMMENDATION_DB_SOURCE=supabase`。")


# ===================================================================
# Sidebar 篩選
# ===================================================================

st.sidebar.header("篩選條件")

df_all = load_all_recommendations()
if df_all.empty:
    st.warning("尚無推薦記錄。請先執行 `uv run python scripts/seed_recommendation_data.py` 建立種子資料。")
    st.stop()

df_all["report_date"] = pd.to_datetime(df_all["report_date"])

date_min = df_all["report_date"].min().date()
date_max = df_all["report_date"].max().date()
date_range = st.sidebar.date_input("日期範圍", value=(date_min, date_max), min_value=date_min, max_value=date_max)

if isinstance(date_range, tuple) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date, end_date = date_min, date_max

max_rank = int(df_all["rank"].max()) if "rank" in df_all.columns else 20
rank_limit = st.sidebar.slider("排名範圍", 1, max_rank, max_rank)

exclude_sim = False
if "is_simulated" in df_all.columns and df_all["is_simulated"].any():
    exclude_sim = st.sidebar.checkbox("排除模擬資料", value=False)

# 過濾
df = df_all[
    (df_all["report_date"].dt.date >= start_date)
    & (df_all["report_date"].dt.date <= end_date)
    & (df_all["rank"] <= rank_limit)
].copy()

if exclude_sim and "is_simulated" in df.columns:
    df = df[df["is_simulated"] == 0]

if df.empty:
    st.info("篩選條件下無資料")
    st.stop()


# ===================================================================
# 區塊 1：整體績效概覽
# ===================================================================

st.header("整體績效概覽")

col1, col2, col3, col4, col5 = st.columns(5)

n_records = len(df)
n_days = df["report_date"].nunique()

for col, t_label, t_col in [
    (col1, "T+5", "return_t5"),
    (col2, "T+10", "return_t10"),
    (col3, "T+20", "return_t20"),
]:
    valid = df[t_col].dropna()
    if valid.empty:
        col.metric(f"{t_label} 平均報酬", "—")
    else:
        avg = valid.mean()
        wr = (valid > 0).mean() * 100
        col.metric(f"{t_label} 平均報酬", f"{avg:+.2f}%")
        col.metric(f"{t_label} 勝率", f"{wr:.0f}%")

col4.metric("推薦筆數", f"{n_records}")
col5.metric("追蹤天數", f"{n_days}")

# 報酬分佈直方圖
st.subheader("報酬分佈")
hist_data = []
for t_label, t_col in [("T+5", "return_t5"), ("T+10", "return_t10"), ("T+20", "return_t20")]:
    valid = df[[t_col]].dropna().copy()
    valid.columns = ["return_pct"]
    valid["期間"] = t_label
    hist_data.append(valid)

if hist_data:
    hist_df = pd.concat(hist_data)
    fig_hist = px.histogram(
        hist_df, x="return_pct", color="期間", barmode="overlay",
        nbins=30, opacity=0.6,
        labels={"return_pct": "報酬率 (%)", "期間": ""},
        title="推薦股票報酬率分佈",
    )
    fig_hist.add_vline(x=0, line_dash="dash", line_color="gray")
    st.plotly_chart(fig_hist, use_container_width=True)


# ===================================================================
# 區塊 2：策略拆分命中率
# ===================================================================

st.header("策略拆分命中率")

# 從篩選後的 df 手動計算（而非用 load_strategy_breakdown，因為要尊重篩選條件）
has_t5 = df[df["return_t5"].notna()].copy()
if has_t5.empty:
    st.info("尚無 T+5 績效資料")
else:
    strategy_stats: dict[str, list[float]] = {}
    for _, row in has_t5.iterrows():
        votes = row.get("strategy_votes")
        if not isinstance(votes, dict):
            continue
        for name, v in votes.items():
            if isinstance(v, dict) and v.get("recent_score", 0) > 0:
                strategy_stats.setdefault(name, []).append(row["return_t5"])

    strat_rows = []
    for name in sorted(strategy_stats, key=lambda x: -len(strategy_stats[x])):
        returns = strategy_stats[name]
        count = len(returns)
        if count < 2:
            continue
        wr = sum(1 for r in returns if r > 0) / count * 100
        avg = sum(returns) / count
        strat_rows.append({"策略": name, "推薦次數": count, "T+5 勝率": f"{wr:.0f}%", "T+5 均報酬": f"{avg:+.2f}%",
                           "_wr": wr, "_avg": avg})

    if strat_rows:
        strat_df = pd.DataFrame(strat_rows)

        # 表格
        st.dataframe(strat_df[["策略", "推薦次數", "T+5 勝率", "T+5 均報酬"]], use_container_width=True, hide_index=True)

        # 長條圖
        fig_strat = px.bar(
            strat_df.sort_values("_wr", ascending=True),
            x="_wr", y="策略", orientation="h",
            labels={"_wr": "T+5 勝率 (%)", "策略": ""},
            title="各策略 T+5 勝率",
            text="_wr",
        )
        fig_strat.update_traces(texttemplate="%{text:.0f}%", textposition="outside")
        fig_strat.add_vline(x=50, line_dash="dash", line_color="gray", annotation_text="50%")
        st.plotly_chart(fig_strat, use_container_width=True)
    else:
        st.info("策略樣本數不足")


# ===================================================================
# 區塊 3：排名 vs 績效
# ===================================================================

st.header("排名 vs 績效")

rank_df = df[["rank", "return_t5"]].dropna()
if rank_df.empty:
    st.info("尚無排名績效資料")
else:
    # 散點圖 + 趨勢線
    fig_scatter = px.scatter(
        rank_df, x="rank", y="return_t5",
        labels={"rank": "推薦排名", "return_t5": "T+5 報酬率 (%)"},
        title="推薦排名 vs T+5 報酬率",
        trendline="ols",
        opacity=0.6,
    )
    fig_scatter.add_hline(y=0, line_dash="dash", line_color="gray")

    # 計算 r²
    if len(rank_df) >= 3:
        from scipy.stats import linregress
        slope, intercept, r_value, p_value, std_err = linregress(rank_df["rank"], rank_df["return_t5"])
        st.caption(f"線性回歸：r² = {r_value**2:.3f}, slope = {slope:.3f}, p = {p_value:.3f}")

    st.plotly_chart(fig_scatter, use_container_width=True)

    # 分組對比
    def _rank_group(r):
        if r <= 5:
            return "Top 5"
        elif r <= 10:
            return "Top 6-10"
        else:
            return "Top 11+"

    rank_df["分組"] = rank_df["rank"].apply(_rank_group)
    group_stats = rank_df.groupby("分組")["return_t5"].agg(["mean", "count"]).reset_index()
    group_stats.columns = ["分組", "平均報酬", "樣本數"]
    # 排序
    order = {"Top 5": 0, "Top 6-10": 1, "Top 11+": 2}
    group_stats["_order"] = group_stats["分組"].map(order)
    group_stats = group_stats.sort_values("_order")

    fig_group = px.bar(
        group_stats, x="分組", y="平均報酬",
        text="平均報酬",
        labels={"平均報酬": "T+5 平均報酬 (%)", "分組": ""},
        title="排名分組 T+5 平均報酬對比",
    )
    fig_group.update_traces(texttemplate="%{text:+.2f}%", textposition="outside")
    fig_group.add_hline(y=0, line_dash="dash", line_color="gray")
    st.plotly_chart(fig_group, use_container_width=True)


# ===================================================================
# 區塊 4：時間趨勢
# ===================================================================

st.header("時間趨勢")

time_df = df[["report_date", "return_t5"]].dropna()
if time_df.empty:
    st.info("尚無時序資料")
else:
    daily_avg = time_df.groupby("report_date")["return_t5"].mean().reset_index()
    daily_avg.columns = ["date", "avg_return"]
    daily_avg = daily_avg.sort_values("date")

    # 滾動均線
    if len(daily_avg) >= 5:
        daily_avg["MA5"] = daily_avg["avg_return"].rolling(5, min_periods=1).mean()
    else:
        daily_avg["MA5"] = daily_avg["avg_return"]

    fig_trend = go.Figure()
    fig_trend.add_trace(go.Scatter(
        x=daily_avg["date"], y=daily_avg["avg_return"],
        mode="markers+lines", name="每日平均 T+5 報酬",
        line=dict(color="lightblue"), marker=dict(size=6),
    ))
    fig_trend.add_trace(go.Scatter(
        x=daily_avg["date"], y=daily_avg["MA5"],
        mode="lines", name="5 日滾動均線",
        line=dict(color="blue", width=2),
    ))
    fig_trend.add_hline(y=0, line_dash="dash", line_color="gray")

    # 版本變更標記
    ver_df = load_version_timeline()
    if not ver_df.empty:
        ver_df["report_date"] = pd.to_datetime(ver_df["report_date"])
        for _, vrow in ver_df.iterrows():
            fig_trend.add_vline(
                x=vrow["report_date"], line_dash="dot", line_color="orange",
                annotation_text=str(vrow["git_commit"])[:7],
                annotation_position="top",
            )

    fig_trend.update_layout(
        title="推薦績效時間趨勢",
        xaxis_title="報告日期",
        yaxis_title="平均 T+5 報酬率 (%)",
    )
    st.plotly_chart(fig_trend, use_container_width=True)
```

**Step 2: 啟動本地測試**

```bash
uv run python main.py --analysis
```

在瀏覽器開啟 http://localhost:8501，切到「推薦追蹤」頁面確認四個區塊正確顯示。

**Step 3: Commit**

```bash
git add analysis/pages/13_推薦追蹤.py
git commit -m "feat: 新增推薦命中率儀表板 — 四個區塊（概覽/策略/排名/趨勢）"
```

---

### Task 5: 更新文件

**Files:**
- Modify: `CLAUDE.md`
- Modify: `analysis/documents/測試說明.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/選股策略藍圖.md`

**Step 1: CLAUDE.md 更新**

量化分析平台表格加入：
```markdown
| `analysis/pages/13_推薦追蹤.py` | 推薦命中率儀表板（整體勝率、策略拆分、排名 vs 績效、時間趨勢） |
```

analysis/utils/ 表格加入：
```markdown
| `analysis/utils/recommendation_db.py` | 推薦追蹤資料層（SQLite/Supabase 切換 + JSONB 轉換） |
```

Scripts 表格加入：
```markdown
| `seed_recommendation_data.py` | 建立本地推薦追蹤 SQLite（報告解析 + 模擬資料） |
```

Tests 表格加入：
```markdown
| `test_recommendation_db.py` | 推薦追蹤資料層測試（SQLite 讀取、JSONB 轉換、策略拆分） |
| `test_seed_recommendation.py` | 種子資料腳本測試（報告解析、模擬資料、SQLite 寫入） |
```

grep 確認所有「12 個」頁面數更新為「13 個」。

**Step 2: 更新測試說明**

在 `analysis/documents/測試說明.md` 加入新測試檔案，更新合計數。

**Step 3: 更新 CHANGELOG.md**

```markdown
### Added
- 推薦命中率儀表板（`13_推薦追蹤.py`）：整體績效、策略拆分命中率、排名 vs 績效、時間趨勢
- 推薦追蹤資料層（`recommendation_db.py`）：SQLite/Supabase 環境變數切換
- 種子資料腳本（`seed_recommendation_data.py`）：三層策略（Supabase dump / Markdown 解析 / 模擬）
```

**Step 4: 更新選股策略藍圖**

將 `docs/選股策略藍圖.md` 中「推薦命中率儀表板」項目標記為 `[x]`。

**Step 5: Commit**

```bash
git add CLAUDE.md "analysis/documents/測試說明.md" CHANGELOG.md "docs/選股策略藍圖.md"
git commit -m "docs: 更新文件 — 推薦命中率儀表板相關說明"
```
