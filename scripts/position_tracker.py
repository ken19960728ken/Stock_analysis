"""持倉追蹤 — 從每日 Top 20 挑選買入、追蹤持倉、產生出場訊號

把無狀態的選股推薦變成可執行的持倉組合：

  SELECT  讀當日 recommendation_history Top 20 → 套 SelectionConfig（top_k +
          min_agree + 加權）挑出實際買入標的 → 開倉（status='open'）。
  TRACK   對每個 open 部位更新 current_price / peak_price / holding_days /
          unrealized_pnl_pct。
  EXIT    沿進場後的價格路徑重播 ExitRule（時間停損 / 停利停損 / 移動停損 /
          出場投票）→ 首次觸發即平倉（status='closed' + exit_* 欄位），並輸出
          當日出場訊號清單供報告/Email。

選法與出場規則來自 analysis.utils.exit_rules 的單一常數（DEFAULT_SELECTION /
DEFAULT_EXIT_RULE），與回測 harness 共用，確保「驗過的規則＝實際在跑的規則」。

⚠️ 一律以 core.db.safe_read_sql 直讀 Supabase（不走 recommendation_db 的 SQLite 預設）。

用法:
    uv run python scripts/position_tracker.py                 # 追蹤最新報告日
    uv run python scripts/position_tracker.py --date 2026-05-28
"""

import argparse
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analysis.utils.exit_rules import (
    CompositeExit,
    DEFAULT_EXIT_RULE,
    DEFAULT_SELECTION,
    ExitRule,
    SelectionConfig,
    StrategyVoteExit,
)
from analysis.utils.indicators import add_atr
from core.db import get_engine, safe_read_sql, save_to_db
from core.logger import setup_logger

logger = setup_logger("position_tracker")

_DDL = """
CREATE TABLE IF NOT EXISTS tracked_positions (
    id BIGSERIAL PRIMARY KEY,
    report_date DATE NOT NULL,
    stock_id TEXT NOT NULL,
    stock_name TEXT,
    entry_date DATE,
    entry_price DOUBLE PRECISION,
    status TEXT DEFAULT 'open',
    current_price DOUBLE PRECISION,
    peak_price DOUBLE PRECISION,
    holding_days INTEGER DEFAULT 0,
    unrealized_pnl_pct DOUBLE PRECISION,
    exit_date DATE,
    exit_price DOUBLE PRECISION,
    exit_reason TEXT,
    realized_pnl_pct DOUBLE PRECISION,
    exit_rule_config JSONB,
    total_score DOUBLE PRECISION,
    agree_count INTEGER,
    git_commit TEXT,
    app_version TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
)
"""

_DDL_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_tracked_positions "
    "ON tracked_positions (report_date, stock_id)"
)

# 每日掃 status='open'；部分索引隨表增長仍維持精簡（open 集恆 ~top_k）
_DDL_OPEN_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_tracked_open "
    "ON tracked_positions (status) WHERE status = 'open'"
)


def _ensure_table(engine) -> None:
    """建立 tracked_positions 表 + 索引（顯式 DDL，避免 to_sql 型別推斷錯誤）。"""
    with engine.connect() as conn:
        conn.execute(text(_DDL))
        conn.execute(text(_DDL_INDEX))
        conn.execute(text(_DDL_OPEN_INDEX))
        conn.commit()


# ---------------------------------------------------------------------------
# 讀取
# ---------------------------------------------------------------------------

def _latest_report_date() -> str | None:
    df = safe_read_sql("SELECT MAX(report_date) AS d FROM recommendation_history")
    if df.empty or pd.isna(df["d"].iloc[0]):
        return None
    return pd.to_datetime(df["d"].iloc[0]).strftime("%Y-%m-%d")


def _load_open_positions() -> pd.DataFrame:
    try:
        return safe_read_sql(
            "SELECT report_date, stock_id, stock_name, entry_date, entry_price "
            "FROM tracked_positions WHERE status = 'open'"
        )
    except Exception:
        return pd.DataFrame()


def _existing_position_ids(report_date: str) -> set:
    """該 report_date 已存在的 stock_id（任何 status），避免同日重複開倉與計數失真。"""
    try:
        df = safe_read_sql(
            "SELECT stock_id FROM tracked_positions WHERE report_date = %(d)s",
            params={"d": report_date},
        )
    except Exception:
        return set()
    if df.empty:
        return set()
    return set(df["stock_id"].astype(str))


def _load_picks(report_date: str) -> pd.DataFrame:
    return safe_read_sql(
        "SELECT * FROM recommendation_history WHERE report_date = %(d)s ORDER BY rank",
        params={"d": report_date},
    )


def _select_to_buy(picks: pd.DataFrame, selection: SelectionConfig) -> pd.DataFrame:
    """套 SelectionConfig：min_agree 門檻 → 加權排序 → 取 top_k。"""
    if picks.empty:
        return picks
    df = picks[picks["agree_count"] >= selection.min_agree].copy()
    if df.empty:
        return df
    if selection.weighting == "score":
        df = df.sort_values("total_score", ascending=False)
    else:
        df = df.sort_values("rank")
    return df.head(selection.top_k)


# ---------------------------------------------------------------------------
# 出場投票（rule D 用，approximate：取最近一筆推薦的 latest_signal）
# ---------------------------------------------------------------------------

def _rule_uses_votes(rule: ExitRule) -> bool:
    if isinstance(rule, StrategyVoteExit):
        return True
    if isinstance(rule, CompositeExit):
        return any(_rule_uses_votes(r) for r in rule.rules)
    return False


def _latest_neg_votes(stock_id: str, as_of: str) -> int:
    df = safe_read_sql(
        "SELECT strategy_votes FROM recommendation_history "
        "WHERE stock_id = %(s)s AND report_date <= %(d)s "
        "ORDER BY report_date DESC LIMIT 1",
        params={"s": stock_id, "d": as_of},
    )
    if df.empty:
        return 0
    votes = df["strategy_votes"].iloc[0]
    if isinstance(votes, str):
        import json
        try:
            votes = json.loads(votes)
        except Exception:
            return 0
    if not isinstance(votes, dict):
        return 0
    return sum(
        1 for v in votes.values()
        if isinstance(v, dict) and v.get("latest_signal", 0) == -1
    )


# ---------------------------------------------------------------------------
# 出場評估（沿進場後價格路徑重播 ExitRule）
# ---------------------------------------------------------------------------

def _price_path(stock_id: str, entry_date) -> pd.DataFrame:
    """進場日（含 40 日緩衝供 ATR 暖機）起的 daily_price，附 ATR。"""
    buf_start = (pd.to_datetime(entry_date) - pd.Timedelta(days=40)).strftime("%Y-%m-%d")
    df = safe_read_sql(
        "SELECT date, high, low, close FROM daily_price "
        "WHERE stock_id = %(s)s AND date >= %(e)s ORDER BY date",
        params={"s": stock_id, "e": buf_start},
    )
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return add_atr(df)


def _evaluate_position(pos: pd.Series, rule: ExitRule, neg_votes: int) -> dict | None:
    """回傳更新後狀態 dict；資料不足回 None（維持原狀）。"""
    entry_price = float(pos["entry_price"])
    entry_date = pd.to_datetime(pos["entry_date"])
    if entry_price <= 0:
        return None

    path = _price_path(pos["stock_id"], entry_date)
    if path.empty:
        return None
    post = path[path["date"] > entry_date].reset_index(drop=True)
    if post.empty:
        return {
            "status": "open", "current_price": entry_price,
            "peak_price": entry_price, "holding_days": 0,
            "unrealized_pnl_pct": 0.0,
        }

    peak = entry_price
    n_bars = len(post)
    for i, bar in enumerate(post.itertuples(index=False), start=1):
        close = float(bar.close)
        peak = max(peak, close)
        atr = float(bar.ATR) if pd.notna(bar.ATR) else None
        # neg_votes 僅有「最近一筆推薦」的快照，無逐日歷史；只在最後一根 bar 套用，
        # 避免把今日票數回溯套到歷史 bar 造成 look-ahead（rule D 用）。
        nv = neg_votes if i == n_bars else 0
        fired, reason = rule.should_exit(
            entry_price=entry_price, close=close, peak_price=peak,
            holding_days=i, atr=atr, neg_votes=nv,
        )
        if fired:
            pnl_pct = round((close / entry_price - 1) * 100, 2)
            return {
                "status": "closed",
                "exit_date": pd.Timestamp(bar.date).strftime("%Y-%m-%d"),
                "exit_price": round(close, 2), "exit_reason": reason,
                "realized_pnl_pct": pnl_pct, "current_price": round(close, 2),
                "peak_price": round(peak, 2), "holding_days": i,
                "unrealized_pnl_pct": pnl_pct,
            }

    cur = float(post.iloc[-1]["close"])
    return {
        "status": "open", "current_price": round(cur, 2),
        "peak_price": round(peak, 2), "holding_days": len(post),
        "unrealized_pnl_pct": round((cur / entry_price - 1) * 100, 2),
    }


def _apply_update(conn, pos: pd.Series, result: dict) -> None:
    fields = dict(result)
    fields["updated_at"] = datetime.now()
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    sql = text(
        f"UPDATE tracked_positions SET {set_clause} "
        "WHERE report_date = :rd AND stock_id = :sid"
    )
    params = {**fields, "rd": pos["report_date"], "sid": pos["stock_id"]}
    conn.execute(sql, params)


# ---------------------------------------------------------------------------
# 開新倉
# ---------------------------------------------------------------------------

def _open_new_positions(
    report_date: str, picks: pd.DataFrame, open_ids: set,
    rule: ExitRule, selection: SelectionConfig,
) -> pd.DataFrame:
    cfg = {"selection": asdict(selection), "exit": repr(rule)}
    rows = []
    for _, r in picks.iterrows():
        sid = str(r["stock_id"])
        if sid in open_ids:
            continue
        ep = r.get("entry_price")
        if pd.isna(ep) or float(ep) <= 0:
            continue
        ep = float(ep)
        rows.append({
            "report_date": report_date, "stock_id": sid,
            "stock_name": r.get("stock_name"), "entry_date": report_date,
            "entry_price": ep, "status": "open", "current_price": ep,
            "peak_price": ep, "holding_days": 0, "unrealized_pnl_pct": 0.0,
            "exit_date": None, "exit_price": None, "exit_reason": None,
            "realized_pnl_pct": None, "exit_rule_config": cfg,
            "total_score": r.get("total_score"), "agree_count": r.get("agree_count"),
            "git_commit": r.get("git_commit"), "app_version": r.get("app_version"),
        })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    save_to_db(df, "tracked_positions")
    return df


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def _holding_row(pos: pd.Series, current, holding_days, unrealized) -> dict:
    """組裝持倉列（無價格資料時以進場價代現價）。"""
    ep = float(pos["entry_price"])
    return {
        "stock_id": str(pos["stock_id"]),
        "stock_name": pos.get("stock_name"),
        "entry_date": pd.Timestamp(pos["entry_date"]).strftime("%Y-%m-%d"),
        "entry_price": ep,
        "current_price": float(current) if current is not None else ep,
        "unrealized_pnl_pct": float(unrealized) if unrealized is not None else 0.0,
        "holding_days": int(holding_days) if holding_days is not None else 0,
    }


def run_position_tracking(
    target_date: str | None = None,
    exit_rule: ExitRule | None = None,
    selection: SelectionConfig | None = None,
) -> dict:
    rule = exit_rule or DEFAULT_EXIT_RULE
    sel = selection or DEFAULT_SELECTION
    engine = get_engine()
    _ensure_table(engine)

    report_date = target_date or _latest_report_date()
    if not report_date:
        logger.info("無推薦記錄，跳過持倉追蹤")
        return {"report_date": None, "opened": 0, "closed": 0, "exits": [], "open_count": 0}

    use_votes = _rule_uses_votes(rule)

    # 1) 追蹤 + 出場：更新既有 open 部位（單一連線批次 UPDATE）
    open_df = _load_open_positions()
    exits: list[dict] = []
    holdings: list[dict] = []
    still_open_ids: set = set()
    pending_updates: list[tuple] = []
    for _, pos in open_df.iterrows():
        neg = _latest_neg_votes(pos["stock_id"], report_date) if use_votes else 0
        result = _evaluate_position(pos, rule, neg)
        if result is None:
            still_open_ids.add(str(pos["stock_id"]))
            holdings.append(_holding_row(pos, None, None, None))
            continue
        pending_updates.append((pos, result))
        if result["status"] == "closed":
            exits.append({
                "stock_id": str(pos["stock_id"]),
                "stock_name": pos.get("stock_name"),
                "entry_date": pd.Timestamp(pos["entry_date"]).strftime("%Y-%m-%d"),
                "exit_date": result["exit_date"],
                "exit_price": result["exit_price"],
                "exit_reason": result["exit_reason"],
                "realized_pnl_pct": result["realized_pnl_pct"],
                "holding_days": result["holding_days"],
            })
        else:
            still_open_ids.add(str(pos["stock_id"]))
            holdings.append(_holding_row(
                pos, result["current_price"], result["holding_days"],
                result["unrealized_pnl_pct"],
            ))

    if pending_updates:
        with engine.connect() as conn:
            for pos, result in pending_updates:
                _apply_update(conn, pos, result)
            conn.commit()

    # 2) 挑選 + 開倉：今日 Top 20 → 選法 → 排除已持有與同日已存在
    exclude = still_open_ids | _existing_position_ids(report_date)
    picks = _select_to_buy(_load_picks(report_date), sel)
    new_df = _open_new_positions(report_date, picks, exclude, rule, sel)

    opens: list[dict] = []
    if not new_df.empty:
        for _, r in new_df.iterrows():
            ep = float(r["entry_price"])
            opens.append({
                "stock_id": str(r["stock_id"]),
                "stock_name": r.get("stock_name"),
                "entry_price": ep,
                "total_score": r.get("total_score"),
                "agree_count": r.get("agree_count"),
            })
            holdings.append({
                "stock_id": str(r["stock_id"]),
                "stock_name": r.get("stock_name"),
                "entry_date": report_date,
                "entry_price": ep,
                "current_price": ep,
                "unrealized_pnl_pct": 0.0,
                "holding_days": 0,
            })

    summary = {
        "report_date": report_date,
        "opened": len(new_df),
        "closed": len(exits),
        "exits": exits,
        "opens": opens,
        "holdings": holdings,
        "open_count": len(still_open_ids) + len(new_df),
    }
    logger.info(
        f"持倉追蹤 {report_date}：開倉 {summary['opened']}、"
        f"平倉 {summary['closed']}、持有中 {summary['open_count']}"
    )
    return summary


def format_tracking_section(summary: dict) -> str:
    """產出可併入報告/Email 的 Markdown 區塊：今日進場 + 今日出場 + 目前持倉。"""
    if not summary or not summary.get("report_date"):
        return ""
    lines = ["## 持倉追蹤與出場訊號\n"]
    lines.append(
        f"> {summary['report_date']}｜開倉 {summary['opened']}、"
        f"平倉 {summary['closed']}、持有中 {summary['open_count']}\n"
    )

    opens = summary.get("opens", [])
    if opens:
        lines.append("### 今日新進場\n")
        lines.append("| 股票 | 進場價 | 加權分數 | 同意策略數 |")
        lines.append("|------|-------|---------|----------|")
        for o in opens:
            name = f"{o['stock_id']} {o.get('stock_name') or ''}".strip()
            score = o.get("total_score")
            score_s = f"{float(score):.2f}" if score is not None and pd.notna(score) else "—"
            agree = o.get("agree_count")
            agree_s = str(int(agree)) if agree is not None and pd.notna(agree) else "—"
            lines.append(f"| {name} | {o['entry_price']:.2f} | {score_s} | {agree_s} |")

    exits = summary.get("exits", [])
    if exits:
        lines.append("### 今日出場訊號\n")
        lines.append("| 股票 | 進場 | 出場 | 出場價 | 報酬 | 持有(交易日) | 原因 |")
        lines.append("|------|------|------|-------|------|------------|------|")
        for e in exits:
            name = f"{e['stock_id']} {e.get('stock_name') or ''}".strip()
            lines.append(
                f"| {name} | {e['entry_date']} | {e['exit_date']} | "
                f"{e['exit_price']:.2f} | {e['realized_pnl_pct']:+.2f}% | "
                f"{e['holding_days']} | {e['exit_reason']} |"
            )

    holdings = summary.get("holdings", [])
    if holdings:
        lines.append("### 目前持倉\n")
        lines.append("| 股票 | 進場日 | 進場價 | 現價 | 未實現 | 持有(交易日) |")
        lines.append("|------|-------|-------|------|-------|------------|")
        for h in sorted(holdings, key=lambda x: x.get("unrealized_pnl_pct", 0), reverse=True):
            name = f"{h['stock_id']} {h.get('stock_name') or ''}".strip()
            lines.append(
                f"| {name} | {h['entry_date']} | {h['entry_price']:.2f} | "
                f"{h['current_price']:.2f} | {h['unrealized_pnl_pct']:+.2f}% | "
                f"{h['holding_days']} |"
            )

    if not opens and not exits and not holdings:
        lines.append("今日無持倉異動。\n")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="持倉追蹤與出場訊號")
    parser.add_argument("--date", help="指定報告日 YYYY-MM-DD（預設最新）")
    args = parser.parse_args()
    summary = run_position_tracking(target_date=args.date)
    print(format_tracking_section(summary))


if __name__ == "__main__":
    main()
