"""
種子資料腳本 — 建立本地 SQLite 推薦追蹤資料庫

⚠️ 開發用：本地 SQLite 資料，後續切換 RECOMMENDATION_DB_SOURCE=supabase 使用真實資料

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


def create_local_db(db_path: Path | None = None) -> Path:
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
    if not records:
        return
    if db_path is None:
        db_path = _SQLITE_PATH
    conn = sqlite3.connect(str(db_path))
    for r in records:
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


_RE_STOCK_HEADER = re.compile(
    r"^### (\d+)\. (\d{4,6})\s+(.+?)\s+—\s+總分\s+([\d.]+)\s+\((\d+)/(\d+)\s+策略同意\)"
)
_RE_CLOSE = re.compile(r"\|\s*收盤價\s*\|\s*([\d.]+)")
_RE_RSI = re.compile(r"\|\s*RSI\(14\)\s*\|\s*([\d.]+)")
_RE_WEEK_RETURN = re.compile(r"\|\s*週漲跌幅\s*\|\s*([+-]?[\d.]+)%")
_RE_AVG_VOL = re.compile(r"\|\s*20日均量\s*\|\s*([\d.]+)\s*張")
_RE_VOTE = re.compile(r"^- (.+?):\s*近期評分\s*\+(\d+)(?:，(\d{2}/\d{2})\s*觸發)?")


def parse_daily_pick_report(content: str, report_date: str) -> list[dict]:
    records = []
    current = None
    for line in content.split("\n"):
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
                "entry_price": None, "rsi": None,
                "week_return": None, "avg_volume_20d": None,
                "strategy_votes": {}, "is_simulated": 0,
            }
            continue
        if current is None:
            continue
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
        m = _RE_VOTE.match(line.strip())
        if m:
            strategy_name = m.group(1)
            score = float(m.group(2))
            signal_date = None
            if m.group(3):
                year = report_date[:4]
                signal_date = f"{year}-{m.group(3).replace('/', '-')}"
            current["strategy_votes"][strategy_name] = {
                "recent_score": score, "signal_date": signal_date,
            }
    if current is not None:
        records.append(current)
    return records


def _backfill_prices(records: list[dict]) -> list[dict]:
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
        ep = r.get("entry_price")
        if not ep or ep <= 0:
            continue
        if n >= 5:
            p5 = float(prices.iloc[4]["close"])
            r["price_t5"] = p5
            r["return_t5"] = round((p5 / ep - 1) * 100, 2)
        if n >= 10:
            p10 = float(prices.iloc[9]["close"])
            r["price_t10"] = p10
            r["return_t10"] = round((p10 / ep - 1) * 100, 2)
        if n >= 20:
            p20 = float(prices.iloc[19]["close"])
            r["price_t20"] = p20
            r["return_t20"] = round((p20 / ep - 1) * 100, 2)
    return records


_MOCK_STOCKS = [
    ("2330", "台積電"), ("2317", "鴻海"), ("2454", "聯發科"), ("2308", "台達電"),
    ("2882", "國泰金"), ("2881", "富邦金"), ("2303", "聯電"), ("3711", "日月光投控"),
    ("2412", "中華電"), ("1301", "台塑"), ("2002", "中鋼"), ("3034", "聯詠"),
    ("2886", "兆豐金"), ("2891", "中信金"), ("5880", "合庫金"),
]
_MOCK_STRATEGIES = ["RSI 反轉", "價值投資", "機器學習選股", "法人跟單", "量價動能", "營收動能"]


def generate_simulated_records(
    existing_dates: list[str], target_days: int = 30, stocks_per_day: int = 15,
) -> list[dict]:
    existing_set = set(existing_dates)
    need_days = target_days - len(existing_set)
    if need_days <= 0:
        return []
    base_date = datetime(2026, 3, 17)
    all_dates = []
    d = base_date
    while len(all_dates) < target_days + 10:
        if d.weekday() < 5:
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
            ret_t5 = max(-15.0, min(15.0, round(random.gauss(0.5, 3.0), 2)))
            ret_t10 = max(-15.0, min(15.0, round(random.gauss(0.8, 4.0), 2)))
            ret_t20 = max(-15.0, min(15.0, round(random.gauss(1.0, 5.0), 2)))
            n_strats = random.randint(2, 4)
            chosen = random.sample(_MOCK_STRATEGIES, n_strats)
            votes = {}
            for s in chosen:
                votes[s] = {"recent_score": float(random.randint(1, 5)), "signal_date": date_str}
            records.append({
                "report_date": date_str, "stock_id": sid, "stock_name": name,
                "rank": rank, "total_score": round(random.uniform(2.0, 8.0), 1),
                "agree_count": n_strats, "total_strategies": 11,
                "entry_price": round(entry_price, 1),
                "rsi": round(random.uniform(30, 70), 1),
                "week_return": round(random.uniform(-5, 10), 1),
                "avg_volume_20d": round(random.uniform(500, 30000), 0),
                "git_commit": "simulated", "app_version": "1.0.0",
                "strategy_votes": votes, "strategy_hashes": {},
                "strategy_weights": {}, "picker_config": {},
                "price_t5": round(entry_price * (1 + ret_t5 / 100), 1),
                "price_t10": round(entry_price * (1 + ret_t10 / 100), 1),
                "price_t20": round(entry_price * (1 + ret_t20 / 100), 1),
                "return_t5": ret_t5, "return_t10": ret_t10, "return_t20": ret_t20,
                "is_simulated": 1,
            })
    return records


def _try_dump_supabase() -> list[dict]:
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
    db_path = create_local_db()
    if mock_only:
        logger.info("純模擬模式")
        records = generate_simulated_records([], target_days=target_days)
        _insert_records(records, db_path)
        logger.info(f"寫入 {len(records)} 筆模擬記錄")
        return
    records = _try_dump_supabase()
    if not records:
        records = _parse_all_reports()
    if records:
        _insert_records(records, db_path)
        logger.info(f"寫入 {len(records)} 筆真實記錄")
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
