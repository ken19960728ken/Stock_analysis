"""
通用策略掃描回測報告

對指定台股執行任何內建策略（16 種）回測，與 0050 買入持有基準比較，
產出個股報告 + 策略層級彙整報告。

用法:
    uv run python scripts/strategy_report.py --list
    uv run python scripts/strategy_report.py --strategy "MA 交叉" --all
    uv run python scripts/strategy_report.py --strategy "MA 交叉" --stocks 2330 2317
    uv run python scripts/strategy_report.py --strategy "法人跟單" --all --top 10 --years 3
    uv run python scripts/strategy_report.py --strategy "RSI 反轉" --all --no-html
    uv run python scripts/strategy_report.py --strategy "MA 交叉" --stocks 2330 --param fast_period=10
"""

import argparse
import gc
import sys
import webbrowser
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
from analysis.utils.backtester import Backtester
from analysis.utils.charts import create_equity_curve
from core.constants import RISK_FREE_RATE, TRADING_DAYS_PER_YEAR, apply_publication_delay
from core.db import get_engine, safe_read_sql
from core.logger import setup_logger

logger = setup_logger("strategy_report")

# 每處理 N 支股票後重置連線池，避免連線池耗盡
CONN_POOL_RESET_INTERVAL = 100

DEFAULT_STOCKS = ["2330", "2317", "2454"]

# 各策略所需的補充資料表（同 3_策略回測.py）
# 注意：「股權集中度」策略需要 shareholder_count 和 holding_percentage，
# 實際資料在 chip_holding_pct 表（people, percent），而非 chip_shareholding。
STRATEGY_DATA_NEEDS = {
    "法人跟單": ["chip_institutional"],
    "融資融券訊號": ["chip_margin"],
    "股權集中度": ["chip_holding_pct"],
    "財報三率": ["financial_reports"],
    "自由現金流": ["financial_reports", "market_value"],
    "價值投資": ["stock_per", "month_revenue"],
    "多因子綜合": ["chip_institutional", "stock_per"],
    "事件驅動": ["dividend_history"],
    "趨勢過濾MA": [],
    "多策略動態組合": ["chip_institutional", "stock_per", "month_revenue"],
    "營收動能": ["month_revenue", "stock_per"],
    "量價動能": [],
    "波動率壓縮突破": [],
}


# ---------------------------------------------------------------------------
# 資料載入（直接 pd.read_sql，不依賴 Streamlit）
# ---------------------------------------------------------------------------

def load_daily_price(engine, stock_id: str, start_date: str) -> pd.DataFrame:
    sql = text(
        "SELECT * FROM daily_price "
        "WHERE stock_id = :sid AND date >= :start "
        "ORDER BY date"
    )
    df = safe_read_sql(sql, params={"sid": stock_id, "start": start_date})
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    return df


def load_stock_name(engine, stock_id: str) -> str:
    sql = text(
        'SELECT "商品名稱" FROM twstock_code WHERE "商品代號" = :sid LIMIT 1'
    )
    with engine.connect() as conn:
        row = conn.execute(sql, {"sid": stock_id}).fetchone()
    return row[0] if row else ""


def load_all_stock_ids(engine) -> list[str]:
    sql = text(
        'SELECT "商品代號" FROM twstock_code '
        "WHERE \"CFICode\" = 'ESVUFR' OR \"商品類型\" = 'ETF' "
        'ORDER BY "商品代號"'
    )
    with engine.connect() as conn:
        rows = conn.execute(sql).fetchall()
    return [r[0] for r in rows]


def load_chip_institutional(engine, stock_id: str, start_date: str) -> pd.DataFrame:
    sql = text(
        "SELECT * FROM chip_institutional "
        "WHERE stock_id = :sid AND date >= :start ORDER BY date"
    )
    df = safe_read_sql(sql, params={"sid": stock_id, "start": start_date})
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    return df


def load_chip_margin(engine, stock_id: str, start_date: str) -> pd.DataFrame:
    sql = text(
        "SELECT * FROM chip_margin "
        "WHERE stock_id = :sid AND date >= :start ORDER BY date"
    )
    df = safe_read_sql(sql, params={"sid": stock_id, "start": start_date})
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    return df


def load_chip_holding_pct(engine, stock_id: str, start_date: str) -> pd.DataFrame:
    """載入股權分散表（持股級距、人數、比例）"""
    sql = text(
        "SELECT * FROM chip_holding_pct "
        "WHERE stock_id = :sid AND date >= :start ORDER BY date"
    )
    df = safe_read_sql(sql, params={"sid": stock_id, "start": start_date})
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    return df


def load_financial_reports(engine, stock_id: str, start_date: str) -> pd.DataFrame:
    sql = text(
        "SELECT * FROM financial_reports "
        "WHERE stock_id = :sid AND date >= :start ORDER BY date"
    )
    df = safe_read_sql(sql, params={"sid": stock_id, "start": start_date})
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    return df


def load_market_value(engine, stock_id: str, start_date: str) -> pd.DataFrame:
    sql = text(
        "SELECT * FROM market_value "
        "WHERE stock_id = :sid AND date >= :start ORDER BY date"
    )
    df = safe_read_sql(sql, params={"sid": stock_id, "start": start_date})
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    return df


def load_stock_per(engine, stock_id: str, start_date: str) -> pd.DataFrame:
    sql = text(
        "SELECT * FROM stock_per "
        "WHERE stock_id = :sid AND date >= :start ORDER BY date"
    )
    df = safe_read_sql(sql, params={"sid": stock_id, "start": start_date})
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    return df


def load_month_revenue(engine, stock_id: str, start_date: str) -> pd.DataFrame:
    sql = text(
        "SELECT * FROM month_revenue "
        "WHERE stock_id = :sid AND date >= :start ORDER BY date"
    )
    df = safe_read_sql(sql, params={"sid": stock_id, "start": start_date})
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    return df


def load_dividend_history(engine, stock_id: str, start_date: str) -> pd.DataFrame:
    sql = text(
        "SELECT * FROM dividend_history "
        "WHERE stock_id = :sid AND date >= :start ORDER BY date"
    )
    df = safe_read_sql(sql, params={"sid": stock_id, "start": start_date})
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    return df


# ---------------------------------------------------------------------------
# 資料合併（對齊 3_策略回測.py 的 _enrich_data 邏輯）
# ---------------------------------------------------------------------------

def enrich_data(engine, df: pd.DataFrame, stock_id: str,
                strategy_name: str, start_date: str) -> pd.DataFrame:
    """根據策略需求載入補充資料並合併到 daily_price"""
    needs = STRATEGY_DATA_NEEDS.get(strategy_name, [])
    if not needs:
        return df

    df = df.sort_values("date").copy()

    for table in needs:
        if table == "chip_institutional":
            extra = load_chip_institutional(engine, stock_id, start_date)
            if not extra.empty:
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
                extra = extra.sort_values("date")
                extra = apply_publication_delay(extra, "chip_institutional")
                df = pd.merge_asof(df, extra, on="date", direction="backward")

        elif table == "chip_margin":
            extra = load_chip_margin(engine, stock_id, start_date)
            if not extra.empty:
                extra = extra.drop(columns=["stock_id"], errors="ignore")
                extra = extra.sort_values("date")
                extra = apply_publication_delay(extra, "chip_margin")
                df = pd.merge_asof(df, extra, on="date", direction="backward")

        elif table == "chip_holding_pct":
            extra = load_chip_holding_pct(engine, stock_id, start_date)
            if not extra.empty:
                # chip_holding_pct 表每日有多筆（不同持股級距），
                # 欄位: date, stock_id, HoldingSharesLevel, people, percent, unit
                # 聚合為每日一筆：
                #   shareholder_count = sum(people)  — 總股東人數
                #   holding_percentage = sum(percent) — 總持股比例
                agg = extra.groupby("date").agg(
                    shareholder_count=("people", "sum"),
                    holding_percentage=("percent", "sum"),
                ).reset_index().sort_values("date")
                agg = apply_publication_delay(agg, "chip_holding_pct")
                df = pd.merge_asof(df, agg, on="date", direction="backward")

        elif table == "financial_reports":
            extra = load_financial_reports(engine, stock_id, start_date)
            if not extra.empty and "type" in extra.columns:
                pivoted = extra.pivot_table(
                    index="date", columns="type", values="value", aggfunc="first",
                ).reset_index()
                pivoted.columns.name = None
                pivoted = pivoted.sort_values("date")
                pivoted = apply_publication_delay(pivoted, "financial_reports")
                df = pd.merge_asof(df, pivoted, on="date", direction="backward")

        elif table == "market_value":
            extra = load_market_value(engine, stock_id, start_date)
            if not extra.empty:
                mv_cols = ["date"] + [c for c in extra.columns if c not in ("date", "stock_id")]
                extra = extra[mv_cols].sort_values("date")
                extra = apply_publication_delay(extra, "market_value")
                df = pd.merge_asof(df, extra, on="date", direction="backward")

        elif table == "stock_per":
            extra = load_stock_per(engine, stock_id, start_date)
            if not extra.empty:
                extra = extra.drop(columns=["stock_id"], errors="ignore")
                extra = extra.sort_values("date")
                extra = apply_publication_delay(extra, "stock_per")
                df = pd.merge_asof(df, extra, on="date", direction="backward")

        elif table == "month_revenue":
            extra = load_month_revenue(engine, stock_id, start_date)
            if not extra.empty:
                extra = extra.drop(columns=["stock_id"], errors="ignore").sort_values("date")
                extra = apply_publication_delay(extra, "month_revenue")
                df = pd.merge_asof(df, extra, on="date", direction="backward")

        elif table == "dividend_history":
            extra = load_dividend_history(engine, stock_id, start_date)
            if not extra.empty:
                extra = extra.drop(columns=["stock_id"], errors="ignore").sort_values("date")
                # 事件驅動策略需要 dividend 欄位
                if "dividend" not in extra.columns:
                    for col in ["cash_dividend", "stock_dividend", "total_dividend"]:
                        if col in extra.columns:
                            extra = extra.rename(columns={col: "dividend"})
                            break
                if "dividend" in extra.columns:
                    div_cols = ["date", "dividend"]
                    extra = extra[[c for c in div_cols if c in extra.columns]]
                    df = df.merge(extra, on="date", how="left")
                    df["dividend"] = df["dividend"].fillna(0)

    return df


# ---------------------------------------------------------------------------
# 0050 買入持有基準
# ---------------------------------------------------------------------------

def calc_benchmark_buyhold(engine, start_date: str,
                           initial_capital: float = 1_000_000) -> dict | None:
    """計算 0050 買入持有績效作為基準比較"""
    df = load_daily_price(engine, "0050", start_date)
    if df.empty or len(df) < 2:
        logger.warning("0050 資料不足，無法計算基準")
        return None

    commission_rate = 0.001425
    first_close = df.iloc[0]["close"]
    shares = int(initial_capital / (first_close * (1 + commission_rate)) / 1000) * 1000
    if shares <= 0:
        return None
    buy_cost = shares * first_close * (1 + commission_rate)
    cash = initial_capital - buy_cost

    equity_vals = cash + shares * df["close"].values
    equity_curve = pd.Series(equity_vals, index=df["date"])

    total_return = (equity_curve.iloc[-1] / initial_capital) - 1
    days = (equity_curve.index[-1] - equity_curve.index[0]).days
    annual_return = (1 + total_return) ** (365 / days) - 1 if days > 0 else 0.0

    returns = equity_curve.pct_change().dropna()
    rf = RISK_FREE_RATE
    if len(returns) > 1 and returns.std() > 1e-12:
        sharpe_ratio = (returns.mean() - rf / TRADING_DAYS_PER_YEAR) / returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR)
    else:
        sharpe_ratio = 0.0

    peak = equity_curve.cummax()
    drawdown_curve = (equity_curve - peak) / peak
    max_drawdown = drawdown_curve.min()

    return {
        "equity_curve": equity_curve,
        "drawdown_curve": drawdown_curve,
        "total_return": total_return,
        "annual_return": annual_return,
        "sharpe_ratio": round(sharpe_ratio, 2),
        "max_drawdown": max_drawdown,
    }


# ---------------------------------------------------------------------------
# 單支股票回測
# ---------------------------------------------------------------------------

def backtest_one(engine, stock_id: str, strategy_name: str, strategy,
                 start_date: str, capital: float = 1_000_000):
    """回傳 (result: BacktestResult | None, name: str)

    Bug 3 修復：低成交量股票可能收盤價標準差為 0，導致 Bollinger Band
    和 RSI 等策略在計算技術指標時出現 ZeroDivisionError。
    在呼叫策略前先檢查收盤價是否有足夠變異性。
    """
    name = ""
    try:
        name = load_stock_name(engine, stock_id)
        logger.info(f"回測 {stock_id} {name} ...")

        daily = load_daily_price(engine, stock_id, start_date)
        if daily.empty or len(daily) < 30:
            logger.warning(f"  {stock_id} 日K資料不足，跳過")
            return None, name

        # Bug 3 保護：收盤價標準差接近 0 的股票，技術指標會出現除零錯誤
        close_std = daily["close"].std()
        if close_std is None or np.isnan(close_std) or close_std < 1e-8:
            logger.warning(
                f"  {stock_id} 收盤價標準差為 0（可能是低流動性或停牌股），跳過"
            )
            return None, name

        df = enrich_data(engine, daily, stock_id, strategy_name, start_date)
        result = Backtester(strategy, capital=capital).run(df)
        return result, name

    except (KeyError, ZeroDivisionError, ValueError) as e:
        # 策略計算中仍可能因個別股票的異常資料而失敗，安全跳過
        logger.warning(f"  {stock_id} {name} 回測失敗（{type(e).__name__}: {e}），跳過")
        return None, name
    except Exception as e:
        # DB 連線或其他未預期錯誤：記錄但不崩潰整個掃描流程
        logger.error(f"  {stock_id} {name} 回測異常（{type(e).__name__}: {e}）")
        return None, name


# ---------------------------------------------------------------------------
# 參數解析
# ---------------------------------------------------------------------------

def parse_params(param_list: list[str] | None) -> dict:
    """解析 --param key=value 格式的參數列表"""
    if not param_list:
        return {}
    params = {}
    for item in param_list:
        if "=" not in item:
            logger.warning(f"忽略無效參數格式: {item}（需要 key=value）")
            continue
        key, val = item.split("=", 1)
        key = key.strip()
        val = val.strip()
        # 嘗試轉換類型
        try:
            params[key] = int(val)
        except ValueError:
            try:
                params[key] = float(val)
            except ValueError:
                params[key] = val
    return params


# ---------------------------------------------------------------------------
# 報告輸出
# ---------------------------------------------------------------------------

def print_stock_result(sid: str, name: str, result, bench: dict | None):
    """印出個股績效 + vs 0050 比較"""
    print(f"\n{'='*60}")
    print(f"  {sid} {name}  績效摘要")
    print(f"{'='*60}")
    print(f"  總報酬率:     {result.total_return:>8.2%}")
    print(f"  年化報酬:     {result.annual_return:>8.2%}")
    print(f"  Sharpe Ratio: {result.sharpe_ratio:>8.2f}")
    print(f"  最大回撤:     {result.max_drawdown:>8.2%}")
    print(f"  勝率:         {result.win_rate:>8.2%}")
    print(f"  交易次數:     {result.trade_count:>8d}")
    print(f"  平均持有天數: {result.avg_holding_days:>8.1f}")
    if bench:
        diff = result.annual_return - bench["annual_return"]
        label = "勝" if diff > 0 else "負"
        print(f"  vs 0050:      {diff:>+8.2%} ({label})")


def print_strategy_summary(results_summary: list[dict], bench: dict | None,
                           strategy_name: str, top_n: int):
    """策略彙整報告"""
    if not results_summary:
        print("\n無任何回測結果")
        return

    df = pd.DataFrame(results_summary)
    total = len(df)
    has_trades = df[df["交易次數"] > 0]
    traded_count = len(has_trades)

    print(f"\n\n{'='*80}")
    print(f"  策略彙整報告: {strategy_name}")
    print(f"{'='*80}")
    print(f"  掃描標的數:   {total}")
    print(f"  有交易標的數: {traded_count}")

    if traded_count > 0:
        print(f"  平均年化報酬: {has_trades['年化報酬(%)'].mean():>8.2f}%")
        print(f"  中位年化報酬: {has_trades['年化報酬(%)'].median():>8.2f}%")
        print(f"  平均 Sharpe:  {has_trades['Sharpe'].mean():>8.2f}")
        print(f"  平均勝率:     {has_trades['勝率(%)'].mean():>8.2f}%")

        if bench:
            bench_annual = bench["annual_return"] * 100
            beat_count = len(has_trades[has_trades["年化報酬(%)"] > bench_annual])
            beat_pct = beat_count / traded_count * 100
            print(f"  勝 0050 比例: {beat_count}/{traded_count} ({beat_pct:.1f}%)")

    # Top N 排名
    if traded_count > 0:
        top = has_trades.nlargest(min(top_n, traded_count), "年化報酬(%)")
        print(f"\n  Top {min(top_n, traded_count)} 排名:")
        print(top.to_string(index=False))

    # 0050 基準
    if bench:
        print(f"\n  0050 買入持有基準:")
        print(f"    總報酬率:   {bench['total_return']:>8.2%}")
        print(f"    年化報酬:   {bench['annual_return']:>8.2%}")
        print(f"    Sharpe:     {bench['sharpe_ratio']:>8.2f}")
        print(f"    最大回撤:   {bench['max_drawdown']:>8.2%}")


def list_strategies():
    """列出所有策略名稱、說明、參數"""
    print(f"\n{'='*80}")
    print("  內建策略一覽（共 {} 個）".format(len(STRATEGY_MAP)))
    print(f"{'='*80}")
    for name, cls in STRATEGY_MAP.items():
        s = cls()
        print(f"\n  策略: {name}")
        print(f"  說明: {s.description}")
        print(f"  參數: {s.get_params()}")


# ---------------------------------------------------------------------------
# 主要執行邏輯（可程式化呼叫）
# ---------------------------------------------------------------------------

def run_report(
    strategy_name: str | None = None,
    stock_ids: list[str] | None = None,
    all_stocks: bool = False,
    top_n: int = 20,
    years: int = 3,
    capital: float = 1_000_000,
    no_html: bool = False,
    param_overrides: dict | None = None,
):
    """執行策略回測報告

    Args:
        strategy_name: 策略名稱（None 則列出策略）
        stock_ids: 指定股票代號
        all_stocks: 全市場掃描
        top_n: 顯示 Top N
        years: 回測年數
        capital: 初始資金
        no_html: 不產生 HTML 圖表
        param_overrides: 策略參數覆蓋
    """
    # 列出策略
    if strategy_name is None:
        list_strategies()
        return

    # 驗證策略名稱
    if strategy_name not in STRATEGY_MAP:
        print(f"未知策略: {strategy_name}")
        print(f"可用策略: {', '.join(STRATEGY_MAP.keys())}")
        return

    # 建立策略實例
    strategy_cls = STRATEGY_MAP[strategy_name]
    strategy = strategy_cls()
    if param_overrides:
        strategy.set_params(**param_overrides)

    engine = get_engine()
    end_date = datetime.now()
    start_date = (end_date - timedelta(days=365 * years)).strftime("%Y-%m-%d")

    # 決定股票清單
    if all_stocks:
        stock_list = load_all_stock_ids(engine)
        logger.info(f"全市場模式：共 {len(stock_list)} 支股票")
    elif stock_ids:
        stock_list = stock_ids
    else:
        stock_list = DEFAULT_STOCKS

    print(f"\n策略回測報告 — {strategy_name}")
    print(f"回測期間: {start_date} ~ {end_date.strftime('%Y-%m-%d')}")
    print(f"股票數量: {len(stock_list)}")
    if param_overrides:
        print(f"參數覆蓋: {param_overrides}")

    # 計算 0050 買入持有基準
    bench = calc_benchmark_buyhold(engine, start_date, capital)
    if bench:
        print(f"\n{'='*60}")
        print("  0050 買入持有基準")
        print(f"{'='*60}")
        print(f"  總報酬率:     {bench['total_return']:>8.2%}")
        print(f"  年化報酬:     {bench['annual_return']:>8.2%}")
        print(f"  Sharpe Ratio: {bench['sharpe_ratio']:>8.2f}")
        print(f"  最大回撤:     {bench['max_drawdown']:>8.2%}")
    else:
        logger.warning("無法計算 0050 基準")

    # 逐支回測（Bug 1 修復：每 N 支股票重置連線池，避免連線耗盡）
    results_summary = []
    chart_data = []
    db_error_count = 0
    MAX_DB_ERRORS = 5  # 連續 DB 錯誤超過此數則中止

    for idx, sid in enumerate(stock_list):
        # Bug 1 核心修復：定期重置 DB 連線池
        if idx > 0 and idx % CONN_POOL_RESET_INTERVAL == 0:
            try:
                engine.dispose()
                gc.collect()
                logger.info(
                    f"已處理 {idx}/{len(stock_list)} 支，重置連線池"
                )
            except Exception as e:
                logger.warning(f"連線池重置失敗: {e}")

        try:
            result, name = backtest_one(
                engine, sid, strategy_name, strategy, start_date, capital
            )
            db_error_count = 0  # 成功則重置 DB 錯誤計數
        except Exception as e:
            # 連線池層級的嚴重錯誤（如 DB 不可用）
            db_error_count += 1
            logger.error(
                f"  {sid} DB 層級錯誤（{db_error_count}/{MAX_DB_ERRORS}）: {e}"
            )
            if db_error_count >= MAX_DB_ERRORS:
                logger.error(
                    f"連續 {MAX_DB_ERRORS} 次 DB 錯誤，嘗試重置連線池後繼續"
                )
                try:
                    engine.dispose()
                    gc.collect()
                    db_error_count = 0
                except Exception:
                    logger.error("連線池重置失敗，中止掃描")
                    break
            continue

        if result is None:
            continue

        print_stock_result(sid, name, result, bench)

        results_summary.append({
            "stock_id": sid,
            "name": name,
            "總報酬率(%)": round(result.total_return * 100, 2),
            "年化報酬(%)": round(result.annual_return * 100, 2),
            "Sharpe": result.sharpe_ratio,
            "最大回撤(%)": round(result.max_drawdown * 100, 2),
            "勝率(%)": round(result.win_rate * 100, 2),
            "交易次數": result.trade_count,
        })
        if not result.equity_curve.empty and result.trade_count > 0:
            chart_data.append((sid, name, result))

    # 策略彙整
    print_strategy_summary(results_summary, bench, strategy_name, top_n)

    # 儲存報告
    reports_dir = PROJECT_ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = strategy_name.replace(" ", "_")

    if results_summary:
        summary_df = pd.DataFrame(results_summary)
        csv_path = reports_dir / f"strategy_{safe_name}_{timestamp}.csv"
        summary_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"\n摘要已輸出: {csv_path}")

    # HTML 權益曲線圖表
    if not no_html and chart_data:
        html_paths = []
        # 只為 Top N 產出圖表
        top_chart = sorted(chart_data, key=lambda x: x[2].annual_return, reverse=True)[:top_n]
        for sid, name, result in top_chart:
            eq = result.equity_curve
            norm_eq = eq / eq.iloc[0] * 100

            norm_bench = None
            if bench:
                b_eq = bench["equity_curve"]
                common_start = eq.index[0]
                b_eq_aligned = b_eq[b_eq.index >= common_start]
                if not b_eq_aligned.empty:
                    norm_bench = b_eq_aligned / b_eq_aligned.iloc[0] * 100

            fig = create_equity_curve(
                norm_eq,
                benchmark=norm_bench,
                drawdown=result.drawdown_curve if not result.drawdown_curve.empty else None,
                title=f"{sid} {name} — {strategy_name} vs 0050 (正規化=100)",
            )
            html_file = reports_dir / f"equity_{safe_name}_{sid}_{timestamp}.html"
            fig.write_html(str(html_file))
            html_paths.append(html_file)

        if html_paths:
            print(f"已產出 {len(html_paths)} 個 HTML 圖表於 reports/")
            webbrowser.open(html_paths[0].as_uri())


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="通用策略掃描回測報告")
    parser.add_argument(
        "--list", action="store_true",
        help="列出所有內建策略",
    )
    parser.add_argument(
        "--strategy", type=str,
        help="策略名稱（如 'MA 交叉'、'法人跟單'）",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--stocks", nargs="+",
        help="指定股票代號",
    )
    group.add_argument(
        "--all", action="store_true",
        help="全市場掃描",
    )
    parser.add_argument(
        "--top", type=int, default=20,
        help="顯示 Top N（預設 20）",
    )
    parser.add_argument(
        "--years", type=int, default=3,
        help="回測年數（預設 3）",
    )
    parser.add_argument(
        "--capital", type=float, default=1_000_000,
        help="初始資金（預設 1,000,000）",
    )
    parser.add_argument(
        "--no-html", action="store_true",
        help="不產生 HTML 權益曲線圖表",
    )
    parser.add_argument(
        "--param", nargs="+",
        help="策略參數覆蓋（格式: key=value）",
    )
    args = parser.parse_args()

    if args.list:
        list_strategies()
        return

    if not args.strategy:
        parser.error("請指定 --strategy 或 --list")

    param_overrides = parse_params(args.param)

    run_report(
        strategy_name=args.strategy,
        stock_ids=args.stocks,
        all_stocks=args.all,
        top_n=args.top,
        years=args.years,
        capital=args.capital,
        no_html=args.no_html,
        param_overrides=param_overrides,
    )


if __name__ == "__main__":
    main()
