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
            for key in params:
                sql = sql.replace(f"%({key})s", f":{key}")
        df = pd.read_sql_query(sql, conn, params=params)
        return _normalize_jsonb(df)
    except Exception:
        return pd.DataFrame()
    finally:
        conn.close()


def load_all_recommendations() -> pd.DataFrame:
    """全量推薦記錄"""
    return _read_sql(
        "SELECT * FROM recommendation_history ORDER BY report_date DESC, rank"
    )


def load_recommendations_by_date(start: str, end: str) -> pd.DataFrame:
    """日期範圍過濾"""
    return _read_sql(
        "SELECT * FROM recommendation_history "
        "WHERE report_date >= %(start)s AND report_date <= %(end)s "
        "ORDER BY report_date DESC, rank",
        params={"start": start, "end": end},
    )


def load_performance_summary() -> dict:
    """整體績效摘要"""
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
    """展開 strategy_votes → 每策略推薦次數 + T+5 勝率"""
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
    for name in sorted(records, key=lambda x: -len(records[x])):
        returns = records[name]
        count = len(returns)
        win_rate = round(sum(1 for r in returns if r > 0) / count * 100, 1) if count else 0.0
        avg_ret = round(sum(returns) / count, 2) if count else 0.0
        rows.append({"strategy": name, "count": count, "win_rate_t5": win_rate, "avg_return_t5": avg_ret})

    return pd.DataFrame(rows)


def load_version_timeline() -> pd.DataFrame:
    """git_commit + app_version 的日期序列（版本變更點）"""
    df = _read_sql(
        "SELECT report_date, git_commit, app_version FROM recommendation_history "
        "ORDER BY report_date"
    )
    if df.empty:
        return pd.DataFrame(columns=["report_date", "git_commit", "app_version"])

    daily = df.groupby("report_date").agg({"git_commit": "first", "app_version": "first"}).reset_index()
    daily = daily.sort_values("report_date")

    changes = [daily.iloc[0]]
    for i in range(1, len(daily)):
        if daily.iloc[i]["git_commit"] != daily.iloc[i - 1]["git_commit"]:
            changes.append(daily.iloc[i])

    return pd.DataFrame(changes).reset_index(drop=True)
