# 選股報告追蹤機制 — 實作計畫

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 為每日選股報告建立版本指紋 + 績效追蹤機制，讓每份推薦都能回溯到策略版本，並自動追蹤 T+5/T+10/T+20 交易日後的表現。

**Architecture:** 新增 DB 表 `recommendation_history` 儲存推薦記錄（含 git SHA + 策略檔案 hash + JSONB 投票明細）。選股報告產出後自動寫入 DB，同時回填歷史推薦的績效。績效追蹤報告獨立產出，不修改原始推薦報告。

**Tech Stack:** Python 3.11, pandas, SQLAlchemy, PostgreSQL (Supabase), hashlib, subprocess (git), importlib.metadata

**設計文件:** `docs/plans/2026-03-20-recommendation-tracking-design.md`

---

### Task 1: DB 白名單 + Constraint 註冊

**Files:**
- Modify: `core/db.py:14-21` (VALID_TABLES)
- Modify: `scripts/db_add_constraints.py:29-47` (CONSTRAINTS)

**Step 1: 在 core/db.py 的 VALID_TABLES 加入 recommendation_history**

```python
VALID_TABLES = frozenset({
    "daily_price", "weekly_price", "monthly_price",
    "financial_reports", "dividend_history", "twstock_code",
    "chip_institutional", "chip_margin", "chip_shareholding",
    "chip_holding_pct", "chip_securities_lending", "chip_short_sale",
    "month_revenue", "stock_per", "market_value",
    "industry_mapping", "industry_classification", "scan_progress",
    "recommendation_history",  # 選股推薦追蹤
})
```

**Step 2: 在 scripts/db_add_constraints.py 的 CONSTRAINTS 加入**

```python
    ("recommendation_history", "uq_recommendation_history", "report_date, stock_id"),
```

加在 `("industry_classification", ...)` 之後。

**Step 3: 在 scripts/daily_stock_picker.py 的 VALID_TABLES 加入**

```python
VALID_TABLES = frozenset({
    "daily_price", "chip_institutional", "stock_per", "month_revenue",
    "twstock_code", "industry_classification",
    "recommendation_history",  # 選股推薦追蹤
})
```

**Step 4: Commit**

```bash
git add core/db.py scripts/db_add_constraints.py scripts/daily_stock_picker.py
git commit -m "feat: 註冊 recommendation_history 到 DB 白名單與 constraint 清單"
```

---

### Task 2: 版本指紋收集函式（TDD）

**Files:**
- Create: `tests/test_recommendation_tracking.py`
- Modify: `scripts/daily_stock_picker.py`

**Step 1: 寫測試 — collect_version_fingerprint**

在 `tests/test_recommendation_tracking.py` 建立：

```python
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
```

**Step 2: 跑測試確認失敗**

```bash
uv run pytest tests/test_recommendation_tracking.py::TestVersionFingerprint -v
```

預期：ImportError（函式尚未存在）

**Step 3: 在 daily_stock_picker.py 實作**

在 imports 區塊加入：

```python
import hashlib
import importlib.metadata
import subprocess
```

在 `_load_name_map()` 函式之前加入：

```python
# ===================================================================
# 版本指紋
# ===================================================================

def collect_version_fingerprint() -> dict:
    """收集 git commit SHA + app 版本號"""
    # git commit
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(PROJECT_ROOT),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        git_sha = "unknown"

    # app version
    try:
        app_ver = importlib.metadata.version("stock-analysis")
    except Exception:
        app_ver = "unknown"

    return {"git_commit": git_sha, "app_version": app_ver}


def collect_strategy_hashes() -> dict[str, str]:
    """計算每個策略檔案的 SHA256，排除 __init__.py 和 base.py"""
    strategy_dir = PROJECT_ROOT / "analysis" / "strategies"
    hashes = {}
    for f in sorted(strategy_dir.glob("*.py")):
        if f.name in ("__init__.py", "base.py"):
            continue
        sha = hashlib.sha256(f.read_bytes()).hexdigest()
        hashes[f.name] = sha
    return hashes
```

**Step 4: 跑測試確認通過**

```bash
uv run pytest tests/test_recommendation_tracking.py::TestVersionFingerprint -v
```

預期：5 PASSED

**Step 5: Commit**

```bash
git add scripts/daily_stock_picker.py tests/test_recommendation_tracking.py
git commit -m "feat: 新增版本指紋收集 — git SHA + 策略檔案 hash"
```

---

### Task 3: save_recommendations() 推薦寫入 DB（TDD）

**Files:**
- Modify: `tests/test_recommendation_tracking.py`
- Modify: `scripts/daily_stock_picker.py`

**Step 1: 寫測試 — save_recommendations**

在 `tests/test_recommendation_tracking.py` 加入：

```python
from scripts.daily_stock_picker import (
    collect_version_fingerprint,
    collect_strategy_hashes,
    save_recommendations,
    STRATEGY_WEIGHTS,
)


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
```

**Step 2: 跑測試確認失敗**

```bash
uv run pytest tests/test_recommendation_tracking.py::TestSaveRecommendations -v
```

**Step 3: 在 daily_stock_picker.py 實作**

在版本指紋函式之後加入：

```python
# ===================================================================
# 推薦記錄儲存
# ===================================================================

def _serialize_votes(votes: dict) -> dict:
    """將 votes 中的 Timestamp 轉為 ISO 字串，確保 JSON 可序列化"""
    serialized = {}
    for name, v in votes.items():
        entry = dict(v)
        sd = entry.get("signal_date")
        if sd is not None and hasattr(sd, "isoformat"):
            entry["signal_date"] = sd.isoformat()[:10]
        elif sd is not None:
            entry["signal_date"] = str(sd)[:10]
        serialized[name] = entry
    return serialized


def _build_recommendation_df(scan_result: dict) -> pd.DataFrame:
    """從 scan_stocks 結果建構推薦記錄 DataFrame"""
    ranked = scan_result["ranked"]
    report_date = scan_result["report_date"]
    ind_map = scan_result.get("ind_map", {})
    name_map = scan_result.get("name_map", {})

    fp = collect_version_fingerprint()
    s_hashes = collect_strategy_hashes()
    config_snapshot = {
        "signal_days": DEFAULT_SIGNAL_DAYS,
        "min_avg_volume": MIN_AVG_VOLUME,
        "min_agree": 2,
        "top_n": len(ranked),
    }

    rows = []
    for i, r in enumerate(ranked, 1):
        sid = r["stock_id"]
        ind = ind_map.get(sid, {})
        rows.append({
            "report_date": report_date,
            "stock_id": sid,
            "stock_name": name_map.get(sid),
            "rank": i,
            "total_score": r["total_score"],
            "agree_count": r["agree_count"],
            "total_strategies": r["total_strategies"],
            "entry_price": r["last_close"],
            "rsi": r.get("rsi"),
            "week_return": r.get("week_return"),
            "avg_volume_20d": r.get("avg_volume_20d"),
            "sector": ind.get("sector"),
            "sub_industry": ind.get("sub_industry"),
            "git_commit": fp["git_commit"],
            "app_version": fp["app_version"],
            "strategy_votes": _serialize_votes(r.get("votes", {})),
            "strategy_hashes": s_hashes,
            "strategy_weights": dict(STRATEGY_WEIGHTS),
            "picker_config": config_snapshot,
        })

    return pd.DataFrame(rows)


def save_recommendations(scan_result: dict) -> bool:
    """將推薦記錄寫入 recommendation_history 表"""
    ranked = scan_result.get("ranked", [])
    if not ranked:
        logger.info("無推薦記錄，跳過儲存")
        return False

    df = _build_recommendation_df(scan_result)
    logger.info(f"儲存 {len(df)} 筆推薦記錄 (report_date={scan_result['report_date']})")
    return save_to_db(df, "recommendation_history")
```

同時在檔案頂部的 import 區塊確認 `save_to_db` 有 import：

```python
from core.db import get_engine, safe_read_sql, save_to_db
```

**Step 4: 跑測試確認通過**

```bash
uv run pytest tests/test_recommendation_tracking.py -v
```

預期：全部 PASSED

**Step 5: Commit**

```bash
git add scripts/daily_stock_picker.py tests/test_recommendation_tracking.py
git commit -m "feat: 新增 save_recommendations — 推薦記錄寫入 DB 含版本指紋"
```

---

### Task 4: backfill_performance() 績效回填（TDD）

**Files:**
- Create: `scripts/performance_tracker.py`
- Create: `tests/test_performance_tracker.py`

**Step 1: 寫測試**

建立 `tests/test_performance_tracker.py`：

```python
"""
績效追蹤測試 — 回填邏輯 + 報告產出

覆蓋：
  - 交易日計算（T+N 是交易日而非日曆日）
  - 部分回填（T+5 可填但 T+20 尚不可）
  - 空資料處理
  - 績效追蹤報告產出
"""

import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock, patch, call

from scripts.performance_tracker import (
    _calc_trading_day_prices,
    backfill_performance,
    generate_performance_report,
)


class TestTradingDayPrices:
    """交易日價格計算"""

    def test_basic_trading_days(self):
        """正常情況：連續交易日"""
        # 模擬 20 個交易日的價格資料
        dates = pd.bdate_range("2026-03-23", periods=25, freq="B")
        prices_df = pd.DataFrame({
            "date": dates,
            "close": [100 + i * 0.5 for i in range(25)],
        })
        result = _calc_trading_day_prices(prices_df)
        # T+5 = 第 5 個交易日（index 4）
        assert result["price_t5"] == 100 + 4 * 0.5
        assert result["price_t10"] == 100 + 9 * 0.5
        assert result["price_t20"] == 100 + 19 * 0.5

    def test_partial_data_only_t5(self):
        """只有 7 個交易日 → 只能算 T+5"""
        dates = pd.bdate_range("2026-03-23", periods=7, freq="B")
        prices_df = pd.DataFrame({
            "date": dates,
            "close": [100 + i for i in range(7)],
        })
        result = _calc_trading_day_prices(prices_df)
        assert result["price_t5"] == 104.0
        assert result["price_t10"] is None
        assert result["price_t20"] is None

    def test_insufficient_data(self):
        """不足 5 個交易日 → 全部 None"""
        dates = pd.bdate_range("2026-03-23", periods=3, freq="B")
        prices_df = pd.DataFrame({
            "date": dates,
            "close": [100, 101, 102],
        })
        result = _calc_trading_day_prices(prices_df)
        assert result["price_t5"] is None
        assert result["price_t10"] is None
        assert result["price_t20"] is None

    def test_empty_df(self):
        result = _calc_trading_day_prices(pd.DataFrame())
        assert result["price_t5"] is None


class TestBackfillPerformance:
    """績效回填"""

    @patch("scripts.performance_tracker.safe_read_sql")
    @patch("scripts.performance_tracker.get_engine")
    def test_backfill_skips_when_no_pending(self, mock_engine, mock_sql):
        """無待回填記錄時不做事"""
        mock_sql.return_value = pd.DataFrame()
        result = backfill_performance()
        assert result == 0

    @patch("scripts.performance_tracker.safe_read_sql")
    @patch("scripts.performance_tracker.get_engine")
    def test_backfill_updates_t5(self, mock_engine, mock_sql):
        """有待回填的 T+5 記錄"""
        # 第一次查詢：待回填記錄
        pending = pd.DataFrame({
            "id": [1],
            "report_date": [pd.Timestamp("2026-03-10")],
            "stock_id": ["2330"],
            "entry_price": [850.0],
            "return_t5": [None],
            "return_t10": [None],
            "return_t20": [None],
        })
        # 第二次查詢：後續交易日價格
        prices = pd.DataFrame({
            "date": pd.bdate_range("2026-03-11", periods=25, freq="B"),
            "close": [855 + i * 0.5 for i in range(25)],
        })
        mock_sql.side_effect = [pending, prices]

        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        result = backfill_performance()
        assert result >= 0  # 不會拋錯


class TestPerformanceReport:
    """績效追蹤報告"""

    @patch("scripts.performance_tracker.safe_read_sql")
    def test_report_with_data(self, mock_sql):
        """有績效資料時產出報告"""
        mock_sql.return_value = pd.DataFrame({
            "report_date": pd.date_range("2026-03-01", periods=5),
            "stock_id": ["2330", "2317", "2454", "2330", "2317"],
            "stock_name": ["台積電", "鴻海", "聯發科", "台積電", "鴻海"],
            "entry_price": [850, 120, 900, 860, 122],
            "return_t5": [1.2, -0.5, 2.0, 0.8, 1.5],
            "return_t10": [2.0, 0.5, 3.0, None, None],
            "return_t20": [3.5, 1.0, None, None, None],
            "rank": [1, 2, 3, 1, 2],
            "agree_count": [4, 3, 5, 4, 3],
            "total_strategies": [11, 11, 11, 11, 11],
            "strategy_votes": [{}] * 5,
            "git_commit": ["abc"] * 5,
        })
        report = generate_performance_report()
        assert "績效追蹤報告" in report
        assert "平均報酬" in report or "勝率" in report

    @patch("scripts.performance_tracker.safe_read_sql")
    def test_report_empty(self, mock_sql):
        """無資料時不會 crash"""
        mock_sql.return_value = pd.DataFrame()
        report = generate_performance_report()
        assert "尚無" in report or "績效追蹤" in report
```

**Step 2: 跑測試確認失敗**

```bash
uv run pytest tests/test_performance_tracker.py -v
```

**Step 3: 建立 scripts/performance_tracker.py**

```python
"""
績效追蹤 — 回填推薦績效 + 產出追蹤報告

用法:
    uv run python scripts/performance_tracker.py                  # 回填 + 產出報告
    uv run python scripts/performance_tracker.py --backfill-only  # 僅回填
    uv run python scripts/performance_tracker.py --report-only    # 僅產報告
"""

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.db import get_engine, safe_read_sql
from core.logger import setup_logger

logger = setup_logger("performance_tracker")


# ===================================================================
# 交易日價格計算
# ===================================================================

def _calc_trading_day_prices(prices_after: pd.DataFrame) -> dict:
    """
    從推薦日之後的交易日價格序列，取 T+5/T+10/T+20 的收盤價。

    Parameters
    ----------
    prices_after : DataFrame
        推薦日之後的交易日價格（已按 date 排序），
        必須包含 date, close 欄位。

    Returns
    -------
    dict : {"price_t5": float|None, "price_t10": ..., "price_t20": ...}
    """
    result = {"price_t5": None, "price_t10": None, "price_t20": None}
    if prices_after is None or prices_after.empty:
        return result

    n = len(prices_after)
    if n >= 5:
        result["price_t5"] = float(prices_after.iloc[4]["close"])
    if n >= 10:
        result["price_t10"] = float(prices_after.iloc[9]["close"])
    if n >= 20:
        result["price_t20"] = float(prices_after.iloc[19]["close"])

    return result


# ===================================================================
# 績效回填
# ===================================================================

def backfill_performance() -> int:
    """
    回填歷史推薦的 T+5/T+10/T+20 績效。

    查詢 recommendation_history 中 return_t5/t10/t20 為 NULL 的記錄，
    從 daily_price 取推薦日之後的交易日收盤價計算報酬率。

    Returns
    -------
    int : 本次更新的記錄數
    """
    # 查詢待回填的記錄
    pending = safe_read_sql(
        "SELECT id, report_date, stock_id, entry_price, "
        "return_t5, return_t10, return_t20 "
        "FROM recommendation_history "
        "WHERE return_t5 IS NULL OR return_t10 IS NULL OR return_t20 IS NULL "
        "ORDER BY report_date"
    )

    if pending.empty:
        logger.info("無待回填記錄")
        return 0

    logger.info(f"待回填記錄: {len(pending)} 筆")

    engine = get_engine()
    updated = 0

    # 按 (stock_id, report_date) 逐筆處理
    for _, row in pending.iterrows():
        sid = row["stock_id"]
        report_date = row["report_date"]
        entry_price = row["entry_price"]
        rec_id = row["id"]

        if entry_price is None or entry_price <= 0:
            continue

        # 取推薦日之後的交易日價格
        prices_after = safe_read_sql(
            "SELECT date, close FROM daily_price "
            "WHERE stock_id = %(sid)s AND date > %(rd)s "
            "ORDER BY date LIMIT 25",
            params={"sid": sid, "rd": report_date},
        )

        if prices_after.empty:
            continue

        td_prices = _calc_trading_day_prices(prices_after)

        # 計算報酬率（只更新目前為 NULL 的欄位）
        updates = {}
        if row["return_t5"] is None and td_prices["price_t5"] is not None:
            updates["price_t5"] = td_prices["price_t5"]
            updates["return_t5"] = round(
                (td_prices["price_t5"] / entry_price - 1) * 100, 2
            )
        if row["return_t10"] is None and td_prices["price_t10"] is not None:
            updates["price_t10"] = td_prices["price_t10"]
            updates["return_t10"] = round(
                (td_prices["price_t10"] / entry_price - 1) * 100, 2
            )
        if row["return_t20"] is None and td_prices["price_t20"] is not None:
            updates["price_t20"] = td_prices["price_t20"]
            updates["return_t20"] = round(
                (td_prices["price_t20"] / entry_price - 1) * 100, 2
            )

        if not updates:
            continue

        # UPDATE
        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        sql = text(f"UPDATE recommendation_history SET {set_clause} WHERE id = :rec_id")
        params = {**updates, "rec_id": rec_id}
        try:
            with engine.connect() as conn:
                conn.execute(sql, params)
                conn.commit()
            updated += 1
        except Exception as e:
            logger.error(f"回填失敗 id={rec_id}: {e}")

    logger.info(f"回填完成: {updated} 筆更新")
    return updated


# ===================================================================
# 績效追蹤報告
# ===================================================================

def generate_performance_report(output_dir: str | None = None) -> str:
    """
    產出績效追蹤 Markdown 報告。

    Returns
    -------
    str : 報告內容（Markdown 字串）
    """
    df = safe_read_sql(
        "SELECT * FROM recommendation_history ORDER BY report_date DESC, rank"
    )

    lines = ["# 選股績效追蹤報告\n"]

    if df.empty:
        lines.append("尚無推薦記錄。系統將從下次產出選股報告時開始追蹤。\n")
        report_text = "\n".join(lines)
        _save_report(report_text, output_dir)
        return report_text

    latest_date = df["report_date"].max()
    earliest_date = df["report_date"].min()
    lines.append(f"> 更新日期：{latest_date}")
    lines.append(f"> 追蹤期間：{earliest_date} ~ {latest_date}")
    lines.append(f"> 累計推薦：{len(df)} 筆\n")

    # 整體績效
    lines.append("## 整體績效\n")
    lines.append("| 指標 | T+5 | T+10 | T+20 |")
    lines.append("|------|-----|------|------|")

    for label, col in [("平均報酬", "return"), ("勝率", "win")]:
        vals = []
        for t in ["t5", "t10", "t20"]:
            col_name = f"return_{t}"
            valid = df[col_name].dropna()
            if valid.empty:
                vals.append("—")
            elif label == "平均報酬":
                vals.append(f"{valid.mean():+.2f}%")
            else:
                vals.append(f"{(valid > 0).mean() * 100:.0f}%")
        lines.append(f"| {label} | {vals[0]} | {vals[1]} | {vals[2]} |")

    # 樣本數
    sample_vals = []
    for t in ["t5", "t10", "t20"]:
        sample_vals.append(str(df[f"return_{t}"].notna().sum()))
    lines.append(f"| 樣本數 | {sample_vals[0]} | {sample_vals[1]} | {sample_vals[2]} |")
    lines.append("")

    # 按策略拆分（從 JSONB 解析）
    _add_strategy_breakdown(df, lines)

    # 最近推薦追蹤
    _add_recent_tracking(df, lines)

    # 版本變更記錄
    _add_version_changes(df, lines)

    lines.append("---\n")
    lines.append("*本報告由績效追蹤系統自動產出*\n")

    report_text = "\n".join(lines)
    _save_report(report_text, output_dir)
    return report_text


def _add_strategy_breakdown(df: pd.DataFrame, lines: list):
    """按策略拆分勝率"""
    # 只分析有 T+5 績效的記錄
    has_t5 = df[df["return_t5"].notna()].copy()
    if has_t5.empty or "strategy_votes" not in has_t5.columns:
        return

    lines.append("## 按策略拆分（投正分的策略）\n")
    lines.append("| 策略 | 推薦次數 | T+5 勝率 | T+5 均報酬 |")
    lines.append("|------|---------|---------|----------|")

    # 統計每個策略「投正分」時的後續表現
    strategy_stats: dict[str, list] = {}
    for _, row in has_t5.iterrows():
        votes = row["strategy_votes"]
        if not isinstance(votes, dict):
            continue
        for name, v in votes.items():
            if isinstance(v, dict) and v.get("recent_score", 0) > 0:
                strategy_stats.setdefault(name, []).append(row["return_t5"])

    for name in sorted(strategy_stats, key=lambda x: -len(strategy_stats[x])):
        returns = strategy_stats[name]
        count = len(returns)
        if count < 3:
            continue
        win_rate = sum(1 for r in returns if r > 0) / count * 100
        avg_ret = sum(returns) / count
        lines.append(f"| {name} | {count} | {win_rate:.0f}% | {avg_ret:+.2f}% |")

    lines.append("")


def _add_recent_tracking(df: pd.DataFrame, lines: list):
    """最近 5 日推薦追蹤"""
    recent_dates = sorted(df["report_date"].unique(), reverse=True)[:5]
    recent = df[df["report_date"].isin(recent_dates)].copy()

    if recent.empty:
        return

    lines.append("## 最近推薦追蹤\n")
    lines.append("| 日期 | 排名 | 股票 | 推薦價 | T+5 | T+10 | T+20 | 版本 |")
    lines.append("|------|------|------|-------|-----|------|------|------|")

    for _, row in recent.iterrows():
        date_str = pd.Timestamp(row["report_date"]).strftime("%m/%d")
        name_str = f"{row['stock_id']} {row.get('stock_name', '')}"
        commit_short = str(row.get("git_commit", ""))[:7]

        t5 = f"{row['return_t5']:+.1f}%" if pd.notna(row.get("return_t5")) else "—"
        t10 = f"{row['return_t10']:+.1f}%" if pd.notna(row.get("return_t10")) else "—"
        t20 = f"{row['return_t20']:+.1f}%" if pd.notna(row.get("return_t20")) else "—"

        lines.append(
            f"| {date_str} | #{row.get('rank', '—')} | {name_str} | "
            f"{row['entry_price']:.1f} | {t5} | {t10} | {t20} | {commit_short} |"
        )
    lines.append("")


def _add_version_changes(df: pd.DataFrame, lines: list):
    """版本變更記錄 — 標記策略 hash 變更的日期"""
    if "strategy_hashes" not in df.columns or "git_commit" not in df.columns:
        return

    # 取每日唯一的 git_commit（從推薦記錄中）
    daily_versions = (
        df.groupby("report_date")
        .agg({"git_commit": "first", "app_version": "first"})
        .sort_index()
    )

    if len(daily_versions) < 2:
        return

    lines.append("## 版本變更記錄\n")
    lines.append("| 日期 | Git Commit | App Version |")
    lines.append("|------|-----------|-------------|")

    prev_commit = None
    for date, row in daily_versions.iterrows():
        commit = str(row["git_commit"])[:7]
        ver = row.get("app_version", "—")
        if prev_commit is None or commit != prev_commit:
            date_str = pd.Timestamp(date).strftime("%Y-%m-%d")
            lines.append(f"| {date_str} | {commit} | {ver} |")
        prev_commit = commit
    lines.append("")


def _save_report(report_text: str, output_dir: str | None = None):
    """寫入 performance_tracking.md"""
    if output_dir is None:
        output_dir = str(PROJECT_ROOT / "reports")
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, "performance_tracking.md")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_text)
    logger.info(f"績效追蹤報告已儲存: {filepath}")


# ===================================================================
# CLI
# ===================================================================

def main():
    parser = argparse.ArgumentParser(description="選股績效追蹤")
    parser.add_argument("--backfill-only", action="store_true", help="僅回填績效")
    parser.add_argument("--report-only", action="store_true", help="僅產出報告")
    parser.add_argument("--output", type=str, default=None, help="報告輸出目錄")
    args = parser.parse_args()

    if args.backfill_only:
        backfill_performance()
    elif args.report_only:
        generate_performance_report(output_dir=args.output)
    else:
        backfill_performance()
        generate_performance_report(output_dir=args.output)


if __name__ == "__main__":
    main()
```

**Step 4: 跑測試確認通過**

```bash
uv run pytest tests/test_performance_tracker.py -v
```

預期：全部 PASSED

**Step 5: Commit**

```bash
git add scripts/performance_tracker.py tests/test_performance_tracker.py
git commit -m "feat: 新增績效追蹤 — 交易日回填 + 追蹤報告產出"
```

---

### Task 5: 每日報告加入版本指紋區塊

**Files:**
- Modify: `scripts/daily_stock_picker.py` (generate_report 函式)
- Modify: `tests/test_recommendation_tracking.py`

**Step 1: 寫測試**

在 `tests/test_recommendation_tracking.py` 加入：

```python
from scripts.daily_stock_picker import generate_report


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
```

**Step 2: 跑測試確認失敗**

```bash
uv run pytest tests/test_recommendation_tracking.py::TestReportVersionBlock -v
```

**Step 3: 修改 generate_report() 函式**

在 `generate_report()` 的風險提示區塊之前（`lines.append("---\n")` 之前），加入版本資訊：

```python
    # 版本資訊
    fp = collect_version_fingerprint()
    lines.append("## 版本資訊\n")
    lines.append(f"- **Git Commit**: {fp['git_commit'][:7]}")
    lines.append(f"- **App Version**: {fp['app_version']}")
    weight_str = ", ".join(f"{k}({v})" for k, v in STRATEGY_WEIGHTS.items())
    lines.append(f"- **策略權重**: {weight_str}")
    lines.append(f"- **選股參數**: signal_days={DEFAULT_SIGNAL_DAYS}, "
                 f"min_agree=2, min_volume={MIN_AVG_VOLUME}張\n")
```

**Step 4: 跑測試確認通過**

```bash
uv run pytest tests/test_recommendation_tracking.py -v
```

**Step 5: Commit**

```bash
git add scripts/daily_stock_picker.py tests/test_recommendation_tracking.py
git commit -m "feat: 每日選股報告加入版本資訊區塊"
```

---

### Task 6: 串接 main.py 流程

**Files:**
- Modify: `main.py:209-225` (run_daily_report)

**Step 1: 修改 run_daily_report()**

```python
def run_daily_report():
    """執行每日選股報告 + 推薦追蹤 + Email 推送。"""
    try:
        from scripts.daily_stock_picker import scan_stocks, build_report, save_recommendations
        from scripts.performance_tracker import backfill_performance, generate_performance_report

        logger.info("開始產出每日選股報告...")

        # 1. 掃描 + 產出報告
        scan_result = scan_stocks()
        if scan_result is None:
            logger.warning("選股掃描失敗")
            return

        report_path = build_report(scan_result)

        # 2. 儲存推薦記錄到 DB（含版本指紋）
        try:
            save_recommendations(scan_result)
        except Exception as e:
            logger.error(f"推薦記錄儲存失敗（不影響報告）: {e}")

        # 3. 回填歷史推薦績效
        try:
            backfill_performance()
        except Exception as e:
            logger.error(f"績效回填失敗（不影響報告）: {e}")

        # 4. 產出績效追蹤報告
        try:
            generate_performance_report()
        except Exception as e:
            logger.error(f"績效追蹤報告產出失敗（不影響報告）: {e}")

        # 5. Email 推送
        if report_path:
            logger.info(f"選股報告已產出: {report_path}")
            try:
                from core.notifier import send_report_email
                send_report_email(report_path)
            except Exception as e:
                logger.error(f"Email 推送異常: {e}")
        else:
            logger.warning("選股報告產出失敗")
    except Exception as e:
        logger.error(f"選股報告產出異常: {e}")
```

**重點**：save_recommendations / backfill / performance_report 各自 try-except，任一失敗不影響主流程和 Email 推送。

**Step 2: 跑全量測試確認無破壞**

```bash
uv run pytest tests/ -v --timeout=60
```

**Step 3: Commit**

```bash
git add main.py
git commit -m "feat: run_daily_report 串接推薦追蹤 — 儲存 + 回填 + 績效報告"
```

---

### Task 7: 建立 DB 表 + 端到端驗證

**Step 1: 在 Supabase SQL Editor 執行建表 SQL**

```sql
CREATE TABLE recommendation_history (
    id               BIGSERIAL PRIMARY KEY,
    report_date      DATE NOT NULL,
    stock_id         VARCHAR(10) NOT NULL,
    stock_name       VARCHAR(50),
    rank             INT,
    total_score      FLOAT,
    agree_count      INT,
    total_strategies INT,
    entry_price      FLOAT,
    rsi              FLOAT,
    week_return      FLOAT,
    avg_volume_20d   FLOAT,
    sector           VARCHAR(50),
    sub_industry     VARCHAR(50),
    git_commit       VARCHAR(40),
    app_version      VARCHAR(20),
    strategy_votes   JSONB,
    strategy_hashes  JSONB,
    strategy_weights JSONB,
    picker_config    JSONB,
    price_t5         FLOAT,
    price_t10        FLOAT,
    price_t20        FLOAT,
    return_t5        FLOAT,
    return_t10       FLOAT,
    return_t20       FLOAT,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(report_date, stock_id)
);

CREATE INDEX idx_rec_hist_date ON recommendation_history(report_date);
CREATE INDEX idx_rec_hist_stock ON recommendation_history(stock_id);
```

**Step 2: 執行 constraint 腳本驗證**

```bash
uv run python scripts/db_add_constraints.py
```

**Step 3: 執行端到端測試（用指定歷史日期）**

```bash
uv run python main.py --pick-stocks --pick-date 2026-03-19
```

確認：
- 報告末尾有「版本資訊」區塊
- 終端機顯示「儲存 N 筆推薦記錄」日誌

**Step 4: 驗證 DB 寫入**

在 Supabase SQL Editor：
```sql
SELECT report_date, stock_id, stock_name, rank, entry_price,
       git_commit, app_version, strategy_weights
FROM recommendation_history
ORDER BY report_date DESC, rank
LIMIT 5;
```

**Step 5: Commit**

```bash
git add -A
git commit -m "feat: 選股推薦追蹤機制完成 — 版本指紋 + 績效回填 + 追蹤報告"
```

---

### Task 8: 更新文件

**Files:**
- Modify: `CLAUDE.md` — Database Tables 加入 `recommendation_history`、Scripts 加入 `performance_tracker.py`、Commands 加入相關指令
- Modify: `analysis/documents/測試說明.md` — 加入新測試檔案
- Modify: `CHANGELOG.md` — 記錄變更

**Step 1: CLAUDE.md 更新**

Database Tables 表格加入：

```markdown
| `recommendation_history` | 選股推薦追蹤（版本指紋 + 績效回填） | `(report_date, stock_id)` |
```

Scripts 表格加入：

```markdown
| `performance_tracker.py` | 績效追蹤（回填 T+5/T+10/T+20 + 追蹤報告） |
```

**Step 2: 更新測試說明**

在 `analysis/documents/測試說明.md` 加入：

```markdown
| `test_recommendation_tracking.py` | 推薦追蹤測試（版本指紋、DB 寫入、序列化） |
| `test_performance_tracker.py` | 績效回填測試（交易日計算、報告產出） |
```

**Step 3: 更新 CHANGELOG.md**

```markdown
### Added
- 選股推薦追蹤機制：每份報告記錄 git commit SHA + 策略檔案 hash + 參數快照
- 績效自動回填：追蹤推薦股票 T+5/T+10/T+20（交易日）的實際表現
- 績效追蹤報告：整體勝率、按策略拆分、版本變更記錄
- 每日選股報告新增「版本資訊」區塊
```

**Step 4: Commit**

```bash
git add CLAUDE.md analysis/documents/測試說明.md CHANGELOG.md
git commit -m "docs: 更新文件 — 推薦追蹤機制的 DB/Script/Test 說明"
```
