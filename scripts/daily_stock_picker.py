"""
每日選股報告 — 多策略投票 + 基本面過濾

用法:
    uv run python scripts/daily_stock_picker.py
    uv run python scripts/daily_stock_picker.py --top 10 --days 7
    uv run python scripts/daily_stock_picker.py --date 2026-03-03
    uv run python scripts/daily_stock_picker.py --output reports/
    uv run python main.py --pick-stocks
    uv run python main.py --pick-stocks --pick-date 2026-03-03
"""

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

# 確保專案根目錄在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analysis.strategies import STRATEGY_MAP
from core.db import get_engine
from core.logger import setup_logger

logger = setup_logger("daily_stock_picker")

# ===================================================================
# 可設定常數
# ===================================================================

# 策略選用清單 + 權重（基於全市場掃描結果，正報酬或優化後達標的策略）
STRATEGY_WEIGHTS = {
    "RSI 反轉": 1.0,
    "價值投資": 0.8,
    "機器學習選股": 0.7,
    "多因子綜合": 0.6,
    "法人跟單": 0.6,
    "趨勢過濾MA": 0.5,
    "多策略動態組合": 0.5,
    "量價動能": 0.7,
    "營收動能": 0.6,
    "波動率壓縮突破": 0.5,
}

# 各策略所需補充資料
STRATEGY_DATA_NEEDS = {
    "RSI 反轉": [],
    "價值投資": ["stock_per", "month_revenue"],
    "機器學習選股": [],
    "多因子綜合": ["chip_institutional", "stock_per"],
    "法人跟單": ["chip_institutional"],
    "趨勢過濾MA": [],
    "多策略動態組合": ["chip_institutional", "stock_per", "month_revenue"],
    "量價動能": [],
    "營收動能": ["month_revenue"],
    "波動率壓縮突破": [],
}

DEFAULT_TOP_N = 20
DEFAULT_SIGNAL_DAYS = 5
MIN_AVG_VOLUME = 500  # 最低 20 日均量（張）
LOOKBACK_TRADE_DAYS = 60  # 載入最近 N 交易日資料

# 合法表名白名單
VALID_TABLES = frozenset({
    "daily_price", "chip_institutional", "stock_per", "month_revenue",
    "twstock_code",
})


# ===================================================================
# 資料載入
# ===================================================================

def _load_table(engine, table: str, stock_id: str, start_date: str,
                end_date: str | None = None) -> pd.DataFrame:
    """載入指定表的資料（可選上限日期）"""
    if table not in VALID_TABLES:
        return pd.DataFrame()
    if end_date:
        query = text(
            f"SELECT * FROM {table} WHERE stock_id = :sid AND date >= :sd AND date <= :ed ORDER BY date"
        )
        params = {"sid": stock_id, "sd": start_date, "ed": end_date}
    else:
        query = text(
            f"SELECT * FROM {table} WHERE stock_id = :sid AND date >= :sd ORDER BY date"
        )
        params = {"sid": stock_id, "sd": start_date}
    try:
        with engine.connect() as conn:
            df = pd.read_sql(query, conn, params=params)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception as e:
        logger.debug(f"載入 {table}/{stock_id} 失敗: {e}")
        return pd.DataFrame()


def load_daily_price(engine, stock_id: str, start_date: str,
                     end_date: str | None = None) -> pd.DataFrame:
    return _load_table(engine, "daily_price", stock_id, start_date, end_date)


def load_all_stock_ids(engine) -> list[str]:
    """從 twstock_code 取得一般股票代碼（排除權證、ETN 等）"""
    query = text(
        'SELECT DISTINCT "商品代號" FROM twstock_code '
        "WHERE \"商品類型\" IN ('股票', 'ETF') "
        'ORDER BY "商品代號"'
    )
    try:
        with engine.connect() as conn:
            result = conn.execute(query)
            return [row[0] for row in result]
    except Exception as e:
        logger.error(f"載入股票清單失敗: {e}")
        return []


def load_stock_name(engine, stock_id: str) -> str:
    query = text('SELECT "商品名稱" FROM twstock_code WHERE "商品代號" = :sid LIMIT 1')
    try:
        with engine.connect() as conn:
            result = conn.execute(query, {"sid": stock_id})
            row = result.fetchone()
            return row[0] if row else stock_id
    except Exception:
        return stock_id


def enrich_data(engine, df: pd.DataFrame, stock_id: str,
                strategy_name: str, start_date: str,
                end_date: str | None = None) -> pd.DataFrame:
    """根據策略需求載入補充資料並合併"""
    needs = STRATEGY_DATA_NEEDS.get(strategy_name, [])
    if not needs:
        return df

    df = df.sort_values("date").copy()

    for table in needs:
        extra = _load_table(engine, table, stock_id, start_date, end_date)
        if extra.empty:
            continue

        if table == "chip_institutional":
            buy_cols = [c for c in extra.columns if c.endswith("_buy")]
            sell_cols = [c for c in extra.columns if c.endswith("_sell")]
            if buy_cols and sell_cols:
                extra["institutional_net_buy"] = (
                    extra[buy_cols].sum(axis=1) - extra[sell_cols].sum(axis=1)
                )
            keep_set = {"date", "institutional_net_buy"}
            for c in extra.columns:
                if (c.endswith("_buy") or c.endswith("_sell")) and c != "institutional_net_buy":
                    keep_set.add(c)
            extra = extra[[c for c in extra.columns if c in keep_set]]
            df = df.merge(extra, on="date", how="left")

        elif table == "stock_per":
            extra = extra.drop(columns=["stock_id"], errors="ignore").sort_values("date")
            df = pd.merge_asof(df, extra, on="date", direction="backward")

        elif table == "month_revenue":
            extra = extra.drop(columns=["stock_id"], errors="ignore").sort_values("date")
            df = pd.merge_asof(df, extra, on="date", direction="backward")

    return df


# ===================================================================
# 選股評分
# ===================================================================

def score_stock(engine, stock_id: str, strategies: dict,
                start_date: str, signal_days: int,
                end_date: str | None = None) -> dict | None:
    """對單支股票用多策略評分，回傳評分結果或 None"""
    df = load_daily_price(engine, stock_id, start_date, end_date)
    if df.empty or len(df) < 20:
        return None

    # 流動性過濾：近 20 日均量 > MIN_AVG_VOLUME 張
    recent_vol = df["volume"].tail(20).mean()
    if recent_vol < MIN_AVG_VOLUME * 1000:  # volume 單位是股，1 張 = 1000 股
        return None

    last_close = df["close"].iloc[-1]
    last_date = df["date"].iloc[-1]

    votes = {}
    for strategy_name, strategy in strategies.items():
        try:
            enriched = enrich_data(engine, df.copy(), stock_id, strategy_name, start_date, end_date)
            result = strategy.generate_signals(enriched)

            # 近 N 天的訊號趨勢
            recent_signals = result["signal"].tail(signal_days)
            recent_score = recent_signals.sum()
            latest_signal = result["signal"].iloc[-1]

            # 找到最近一個非零訊號的日期
            nonzero = result[result["signal"] != 0]
            signal_date = nonzero["date"].iloc[-1] if not nonzero.empty and "date" in nonzero.columns else None

            votes[strategy_name] = {
                "latest_signal": int(latest_signal),
                "recent_score": float(recent_score),
                "signal_date": signal_date,
            }
        except Exception as e:
            logger.debug(f"  {stock_id}/{strategy_name} 評分失敗: {e}")
            votes[strategy_name] = {
                "latest_signal": 0,
                "recent_score": 0.0,
                "signal_date": None,
            }

    # 加權投票
    total_score = sum(
        v["recent_score"] * STRATEGY_WEIGHTS.get(name, 0.5)
        for name, v in votes.items()
    )
    agree_count = sum(1 for v in votes.values() if v["recent_score"] > 0)

    # 過去 5 日表現
    if len(df) >= 5:
        week_return = (df["close"].iloc[-1] / df["close"].iloc[-5] - 1) * 100
        week_vol_change = (
            df["volume"].tail(5).mean() / df["volume"].tail(20).mean() - 1
        ) * 100 if df["volume"].tail(20).mean() > 0 else 0
    else:
        week_return = 0
        week_vol_change = 0

    # RSI 計算
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = (100 - (100 / (1 + rs))).iloc[-1] if len(df) >= 14 else None

    return {
        "stock_id": stock_id,
        "total_score": total_score,
        "agree_count": agree_count,
        "total_strategies": len(strategies),
        "votes": votes,
        "last_close": last_close,
        "last_date": last_date,
        "week_return": week_return,
        "week_vol_change": week_vol_change,
        "rsi": rsi,
        "avg_volume_20d": recent_vol / 1000,  # 轉換為張
    }


def filter_and_rank(results: list[dict], top_n: int,
                    min_agree: int = 2) -> list[dict]:
    """過濾 + 排名"""
    filtered = [
        r for r in results
        if r["agree_count"] >= min_agree and r["total_score"] > 0
    ]
    filtered.sort(key=lambda x: x["total_score"], reverse=True)
    return filtered[:top_n]


# ===================================================================
# 報告生成
# ===================================================================

def generate_report(ranked: list[dict], engine, strategies_used: list[str],
                    total_scanned: int, report_date: str) -> str:
    """生成 Markdown 報告"""
    lines = []
    lines.append(f"# 每日選股報告 — {report_date}\n")
    lines.append("## 報告摘要\n")
    lines.append(f"- **策略組合**: {', '.join(strategies_used)}")
    lines.append(f"- **掃描標的**: {total_scanned} 支")
    lines.append(f"- **篩選結果**: {len(ranked)} 支推薦")
    lines.append(f"- **最低門檻**: 至少 2 個策略給正分\n")

    if not ranked:
        lines.append("## 無符合條件的股票\n")
        lines.append("所有策略在最近交易日均未產生明確買入訊號。\n")
    else:
        lines.append("## 推薦清單\n")
        for i, r in enumerate(ranked, 1):
            stock_name = load_stock_name(engine, r["stock_id"])
            lines.append(
                f"### {i}. {r['stock_id']} {stock_name} — "
                f"總分 {r['total_score']:.1f} "
                f"({r['agree_count']}/{r['total_strategies']} 策略同意)\n"
            )

            lines.append("| 指標 | 數值 |")
            lines.append("|------|------|")
            lines.append(f"| 收盤價 | {r['last_close']:.1f} |")
            lines.append(f"| 週漲跌幅 | {r['week_return']:+.1f}% |")
            lines.append(f"| 週量能變化 | {r['week_vol_change']:+.1f}% |")
            if r["rsi"] is not None:
                lines.append(f"| RSI(14) | {r['rsi']:.1f} |")
            lines.append(f"| 20日均量 | {r['avg_volume_20d']:.0f} 張 |")
            lines.append("")

            lines.append("**選股理由**:")
            for name, v in r["votes"].items():
                if v["recent_score"] > 0:
                    date_str = ""
                    if v["signal_date"] is not None:
                        date_str = f"，{pd.Timestamp(v['signal_date']).strftime('%m/%d')} 觸發"
                    lines.append(
                        f"- {name}: 近期評分 {v['recent_score']:+.0f}{date_str}"
                    )
            lines.append("")

    lines.append("---\n")
    lines.append("## 風險提示\n")
    lines.append("- 本報告為量化模型自動產出，不構成投資建議")
    lines.append("- 回測績效不代表未來表現")
    lines.append("- 市場風險無法完全預測，請做好資金管理\n")

    return "\n".join(lines)


# ===================================================================
# 主流程
# ===================================================================

def run_daily_pick(top_n: int = DEFAULT_TOP_N, signal_days: int = DEFAULT_SIGNAL_DAYS,
                   output_dir: str | None = None, target_date: str | None = None) -> str | None:
    """
    執行每日選股流程，回傳報告檔案路徑。

    Parameters
    ----------
    top_n : int
        選出 Top N 股票
    signal_days : int
        考慮最近 N 天的訊號
    output_dir : str | None
        報告輸出目錄，None 則用預設 reports/
    target_date : str | None
        指定報告日期（格式 YYYY-MM-DD），None 則自動取 DB 中最新資料日期

    Returns
    -------
    str | None
        報告檔案路徑，失敗則 None
    """
    # 連線 DB
    try:
        engine = get_engine()
    except Exception as e:
        logger.error(f"DB 連線失敗: {e}")
        print(f"錯誤: DB 連線失敗 — {e}")
        return None

    # 決定報告日期
    if target_date:
        report_date = target_date
    else:
        # 自動取 DB 中最新資料日期
        try:
            with engine.connect() as conn:
                max_date = conn.execute(
                    text("SELECT MAX(date) FROM daily_price")
                ).fetchone()[0]
            report_date = max_date.strftime("%Y-%m-%d") if max_date else datetime.now().strftime("%Y-%m-%d")
        except Exception:
            report_date = datetime.now().strftime("%Y-%m-%d")

    start_date = (datetime.strptime(report_date, "%Y-%m-%d") - timedelta(days=LOOKBACK_TRADE_DAYS * 2)).strftime("%Y-%m-%d")
    # 指定日期時限制資料上限，避免看到未來資料
    end_date = report_date if target_date else None

    print(f"\n{'='*60}")
    print(f"每日選股報告 — {report_date}")
    print(f"{'='*60}\n")

    # 初始化策略
    strategies = {}
    strategies_used = []
    for name in STRATEGY_WEIGHTS:
        if name in STRATEGY_MAP:
            strategies[name] = STRATEGY_MAP[name]()
            strategies_used.append(name)

    print(f"使用策略: {', '.join(strategies_used)}")

    # 載入股票清單
    stock_ids = load_all_stock_ids(engine)
    if not stock_ids:
        print("錯誤: 無法載入股票清單")
        return None

    print(f"掃描標的: {len(stock_ids)} 支")
    print(f"考慮最近 {signal_days} 天訊號，選出 Top {top_n}\n")

    # 逐支評分
    results = []
    total = len(stock_ids)
    for i, sid in enumerate(stock_ids):
        if (i + 1) % 100 == 0 or i == 0:
            print(f"  掃描進度: {i+1}/{total} ({(i+1)/total*100:.0f}%)")

        result = score_stock(engine, sid, strategies, start_date, signal_days, end_date)
        if result is not None:
            results.append(result)

    print(f"\n通過流動性過濾: {len(results)} 支")

    # 排名
    ranked = filter_and_rank(results, top_n)
    print(f"最終推薦: {len(ranked)} 支\n")

    # 生成報告
    report = generate_report(ranked, engine, strategies_used, len(stock_ids), report_date)

    # 寫入檔案
    if output_dir is None:
        output_dir = str(PROJECT_ROOT / "reports")
    os.makedirs(output_dir, exist_ok=True)
    filename = f"daily_pick_{report_date}.md"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"報告已儲存: {filepath}")

    # 列印摘要
    if ranked:
        print(f"\n{'='*60}")
        print(f"Top {min(5, len(ranked))} 推薦:")
        print(f"{'='*60}")
        for i, r in enumerate(ranked[:5], 1):
            name = load_stock_name(engine, r["stock_id"])
            print(
                f"  {i}. {r['stock_id']} {name} — "
                f"分數 {r['total_score']:.1f}, "
                f"{r['agree_count']}/{r['total_strategies']} 策略同意, "
                f"週報酬 {r['week_return']:+.1f}%"
            )

    return filepath


def main():
    parser = argparse.ArgumentParser(description="每日選股報告 — 多策略投票")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP_N, help=f"Top N (預設 {DEFAULT_TOP_N})")
    parser.add_argument("--days", type=int, default=DEFAULT_SIGNAL_DAYS, help=f"考慮最近 N 天訊號 (預設 {DEFAULT_SIGNAL_DAYS})")
    parser.add_argument("--output", type=str, default=None, help="報告輸出目錄")
    parser.add_argument("--date", type=str, default=None, help="指定報告日期 (格式: YYYY-MM-DD，預設自動取 DB 最新日期)")
    args = parser.parse_args()

    run_daily_pick(top_n=args.top, signal_days=args.days, output_dir=args.output, target_date=args.date)


if __name__ == "__main__":
    main()
