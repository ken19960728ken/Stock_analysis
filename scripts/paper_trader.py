"""
Paper Trading 引擎 — 每日模擬交易

每日收盤後自動：
1. 載入策略淘汰賽篩選出的策略
2. 掃描全市場訊號
3. 組合構建 + 風控檢查
4. 模擬買賣（動態滑價 + 流動性限制）
5. 更新 Paper Portfolio → DB
6. 產生報告 + 告警

用法:
    uv run python scripts/paper_trader.py
    uv run python main.py --paper-trading
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# 確保專案根目錄在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analysis.strategies import STRATEGY_MAP
from analysis.utils.data_loader import _compute_revenue_yoy
from core.constants import apply_publication_delay
from core.db import get_engine, safe_read_sql, save_to_db
from core.logger import setup_logger

logger = setup_logger("paper_trader")

# ===================================================================
# 設定常數
# ===================================================================

DEFAULT_INITIAL_CAPITAL = 10_000_000  # 1000 萬
COMMISSION_RATE = 0.001425            # 券商手續費 0.1425%
SELL_TAX_RATE = 0.003                 # 證交稅 0.3%
LOT_SIZE = 1000                       # 台股整張 = 1000 股
MIN_AVG_VOLUME = 500                  # 最低 20 日均量（張）
MAX_POSITIONS = 10                    # 最大同時持股
MAX_PARTICIPATION = 0.10              # 日量佔比上限
LOOKBACK_TRADE_DAYS = 60              # 載入最近 N 交易日

# 動態滑價參數
BASE_SLIPPAGE = 0.0005                # 買賣價差 0.05%
IMPACT_COEFF = 0.1                    # Kyle lambda

# 各策略所需補充資料
STRATEGY_DATA_NEEDS: dict[str, list[str]] = {
    "RSI 反轉": [],
    "價值投資": ["stock_per", "month_revenue"],
    "機器學習選股": [],
    "多因子綜合": ["chip_institutional", "stock_per"],
    "法人跟單": ["chip_institutional"],
    "趨勢過濾MA": [],
    "多策略動態組合": ["chip_institutional", "stock_per", "month_revenue"],
    "量價動能": [],
    "營收動能": ["month_revenue", "stock_per"],
    "波動率壓縮突破": [],
    "次產業輪動": ["month_revenue", "chip_institutional"],
    "當沖情緒反轉": ["day_trading"],
    "外資連續買超": ["chip_broker"],
    "散戶vs主力": ["day_trading", "chip_broker"],
    "官股護盤": ["chip_gov_bank"],
}


# ===================================================================
# 資料載入（重用 daily_stock_picker 模式）
# ===================================================================

def _load_table_chunked(
    table_name: str, start_date: str, end_date: str | None = None,
) -> pd.DataFrame:
    """分段查詢大表，避免 Supabase statement_timeout"""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d") if end_date else datetime.now()

    chunks: list[pd.DataFrame] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=44), end)
        sql = f"SELECT * FROM {table_name} WHERE date >= %(sd)s AND date <= %(ed)s"
        p = {"sd": cursor.strftime("%Y-%m-%d"), "ed": chunk_end.strftime("%Y-%m-%d")}
        df = safe_read_sql(sql, params=p, timeout_ms=300_000)
        if not df.empty:
            chunks.append(df)
        cursor = chunk_end + timedelta(days=1)

    return pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()


def _build_stock_cache(df: pd.DataFrame | None) -> dict[str, pd.DataFrame]:
    """依 stock_id 分組"""
    if df is None or df.empty:
        return {}
    return {
        sid: grp.reset_index(drop=True)
        for sid, grp in df.groupby("stock_id", sort=False)
    }


def _load_all_tables(
    start_date: str, end_date: str | None = None,
) -> dict[str, pd.DataFrame]:
    """批量載入所有需要的表格"""
    tables: dict[str, pd.DataFrame] = {}

    tables["daily_price"] = _load_table_chunked("daily_price", start_date, end_date)

    for tbl in ["chip_institutional", "stock_per"]:
        tables[tbl] = _load_table_chunked(tbl, start_date, end_date)

    # month_revenue 往前推 450 天
    rev_start = (
        datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=450)
    ).strftime("%Y-%m-%d")
    sql = "SELECT * FROM month_revenue WHERE date >= %(sd)s"
    p: dict = {"sd": rev_start}
    if end_date:
        sql += " AND date <= %(ed)s"
        p["ed"] = end_date
    rev_df = safe_read_sql(sql, params=p, timeout_ms=300_000)
    rev_df = _compute_revenue_yoy(rev_df)
    tables["month_revenue"] = rev_df

    # 載入較小的補充表
    for tbl in ["day_trading", "chip_broker", "chip_gov_bank"]:
        try:
            tables[tbl] = _load_table_chunked(tbl, start_date, end_date)
        except Exception:
            tables[tbl] = pd.DataFrame()

    return tables


def _load_stock_ids() -> list[str]:
    """從 twstock_code 載入所有股票代碼"""
    sql = """SELECT "商品代號" AS stock_id FROM twstock_code
             WHERE "CFICode" = 'ESVUFR' OR "CFICode" LIKE 'CEE%%'"""
    df = safe_read_sql(sql)
    return df["stock_id"].tolist() if not df.empty else []


def _enrich_for_strategy(
    df: pd.DataFrame,
    stock_id: str,
    strategy_name: str,
    chip_cache: dict, per_cache: dict, rev_cache: dict,
    extra_caches: dict[str, dict] | None = None,
    ind_map: dict[str, dict] | None = None,
) -> pd.DataFrame:
    """根據策略需求合併補充資料"""
    needs = STRATEGY_DATA_NEEDS.get(strategy_name, [])
    if not needs:
        return df

    df = df.sort_values("date").copy()

    if strategy_name == "次產業輪動" and ind_map:
        info = ind_map.get(stock_id, {})
        df["sub_industry"] = info.get("sub_industry")

    for table in needs:
        if table == "chip_institutional":
            extra = chip_cache.get(stock_id, pd.DataFrame())
        elif table == "stock_per":
            extra = per_cache.get(stock_id, pd.DataFrame())
        elif table == "month_revenue":
            extra = rev_cache.get(stock_id, pd.DataFrame())
        elif extra_caches:
            extra = extra_caches.get(table, {}).get(stock_id, pd.DataFrame())
        else:
            continue

        if extra.empty:
            continue

        if table == "chip_institutional":
            extra = extra.copy()
            buy_cols = [c for c in extra.columns if c.endswith("_buy")]
            sell_cols = [c for c in extra.columns if c.endswith("_sell")]
            if buy_cols and sell_cols:
                extra["institutional_net_buy"] = (
                    extra[buy_cols].sum(axis=1) - extra[sell_cols].sum(axis=1)
                )
            keep_set = {"date", "institutional_net_buy"}
            for c in extra.columns:
                if c.endswith("_buy") or c.endswith("_sell"):
                    keep_set.add(c)
            extra = extra[[c for c in extra.columns if c in keep_set]]
            extra = extra.sort_values("date")
            extra = apply_publication_delay(extra, "chip_institutional")
            df = pd.merge_asof(df, extra, on="date", direction="backward")

        elif table == "stock_per":
            extra = extra.drop(columns=["stock_id"], errors="ignore").sort_values("date")
            extra = apply_publication_delay(extra, "stock_per")
            df = pd.merge_asof(df, extra, on="date", direction="backward")

        elif table == "month_revenue":
            extra = extra.drop(columns=["stock_id"], errors="ignore").sort_values("date")
            extra = apply_publication_delay(extra, "month_revenue")
            df = pd.merge_asof(df, extra, on="date", direction="backward")

        elif table in ("day_trading", "chip_broker", "chip_gov_bank"):
            extra = extra.drop(columns=["stock_id"], errors="ignore").sort_values("date")
            extra = apply_publication_delay(extra, table)
            df = pd.merge_asof(df, extra, on="date", direction="backward")

    return df


# ===================================================================
# 訊號掃描
# ===================================================================

def _scan_signals(
    strategies: list[tuple[str, type]],
    price_cache: dict[str, pd.DataFrame],
    chip_cache: dict, per_cache: dict, rev_cache: dict,
    extra_caches: dict[str, dict] | None = None,
    ind_map: dict[str, dict] | None = None,
) -> dict[str, dict[str, int]]:
    """對全市場股票跑已篩選策略的 generate_signals()

    Returns: {stock_id: {strategy_name: signal_value (1/-1/0)}}
    """
    results: dict[str, dict[str, int]] = {}
    total = len(price_cache)
    scanned = 0

    for stock_id, price_df in price_cache.items():
        if price_df.empty or len(price_df) < 20:
            continue

        # 流動性過濾
        recent_vol = price_df["volume"].tail(20).mean()
        if recent_vol < MIN_AVG_VOLUME * 1000:
            continue

        # 確保 date 為 datetime
        if "date" in price_df.columns and not pd.api.types.is_datetime64_any_dtype(price_df["date"]):
            price_df = price_df.copy()
            price_df["date"] = pd.to_datetime(price_df["date"])

        stock_signals: dict[str, int] = {}
        for strategy_name, strategy_cls in strategies:
            try:
                enriched = _enrich_for_strategy(
                    price_df.copy(), stock_id, strategy_name,
                    chip_cache, per_cache, rev_cache, extra_caches, ind_map,
                )
                strategy = strategy_cls()
                sig_df = strategy.generate_signals(enriched)

                if "signal" in sig_df.columns and len(sig_df) > 0:
                    # 取最後一天的訊號
                    last_signal = int(sig_df["signal"].iloc[-1])
                    stock_signals[strategy_name] = last_signal
            except Exception:
                pass

        if stock_signals:
            results[stock_id] = stock_signals
            scanned += 1

    logger.info(f"掃描完成：{scanned}/{total} 支股票有訊號")
    return results


# ===================================================================
# 訂單構建 + 模擬執行
# ===================================================================

def _construct_orders(
    signals: dict[str, dict[str, int]],
    holdings: pd.DataFrame,
    cash: float,
    total_equity: float,
    price_cache: dict[str, pd.DataFrame],
    risk_state,
    risk_limits,
    industry_map: pd.DataFrame | None = None,
    portfolio_returns: pd.Series | None = None,
) -> list[dict]:
    """將訊號轉換為買賣訂單

    Args:
        signals: {stock_id: {strategy_name: signal}}
        holdings: 當前持倉 [stock_id, shares, entry_price, strategy_name, ...]
        cash: 可用現金
        total_equity: 總資產
        price_cache: {stock_id: price_df}
        risk_state: RiskState
        risk_limits: RiskLimits
        industry_map: 產業分類
        portfolio_returns: 近 60 日組合報酬

    Returns: list of order dicts
    """
    from scripts.paper_risk_control import check_risk_constraints

    orders: list[dict] = []
    held_stocks = set(holdings["stock_id"].tolist()) if not holdings.empty else set()

    # 收集當前價格
    current_prices: dict[str, float] = {}
    for sid, pdf in price_cache.items():
        if not pdf.empty:
            current_prices[sid] = float(pdf["close"].iloc[-1])

    # === 賣出訂單 ===
    for _, row in holdings.iterrows():
        sid = row["stock_id"]
        stock_signals = signals.get(sid, {})
        # 任何策略發出 -1 就賣出
        should_sell = any(v == -1 for v in stock_signals.values())
        if should_sell:
            orders.append({
                "stock_id": sid,
                "side": "sell",
                "shares": int(row["shares"]),
                "price": current_prices.get(sid, float(row.get("current_price", 0))),
                "strategy_name": row.get("strategy_name", "unknown"),
                "reason": "signal",
            })

    # === 買入訂單 ===
    # 收集所有買入候選
    buy_candidates: list[dict] = []
    for stock_id, stock_signals in signals.items():
        if stock_id in held_stocks:
            continue
        # 任何策略發出 +1
        buy_strategies = [name for name, sig in stock_signals.items() if sig == 1]
        if not buy_strategies:
            continue
        price = current_prices.get(stock_id)
        if not price or price <= 0:
            continue
        # 用訊號數量作為優先級
        buy_candidates.append({
            "stock_id": stock_id,
            "buy_strategies": buy_strategies,
            "agree_count": len(buy_strategies),
            "price": price,
        })

    # 依多策略共識度排序
    buy_candidates.sort(key=lambda x: x["agree_count"], reverse=True)

    # 計算可建倉數量
    sell_count = sum(1 for o in orders if o["side"] == "sell")
    current_positions = len(held_stocks) - sell_count
    available_slots = MAX_POSITIONS - max(current_positions, 0)

    if available_slots <= 0 or not buy_candidates:
        return orders

    # 等權分配
    candidates_to_buy = buy_candidates[:available_slots]
    per_position_capital = cash / len(candidates_to_buy) if candidates_to_buy else 0

    for candidate in candidates_to_buy:
        stock_id = candidate["stock_id"]
        price = candidate["price"]
        strategy_name = candidate["buy_strategies"][0]  # 主要觸發策略

        # 計算股數（整張取整）
        raw_shares = per_position_capital / price
        shares = int(raw_shares / LOT_SIZE) * LOT_SIZE
        if shares <= 0:
            continue

        # 流動性限制
        pdf = price_cache.get(stock_id, pd.DataFrame())
        if not pdf.empty:
            avg_vol = pdf["volume"].tail(20).mean()
            if avg_vol > 0:
                max_shares = int(avg_vol * MAX_PARTICIPATION / LOT_SIZE) * LOT_SIZE
                shares = min(shares, max_shares)
                if shares <= 0:
                    continue

        order = {
            "stock_id": stock_id,
            "side": "buy",
            "shares": shares,
            "price": price,
            "strategy_name": strategy_name,
            "reason": "signal",
        }

        # 風控檢查
        allowed, reason = check_risk_constraints(
            order=order,
            holdings=holdings,
            cash=cash,
            total_equity=total_equity,
            risk_state=risk_state,
            risk_limits=risk_limits,
            industry_map=industry_map,
            current_prices=current_prices,
            portfolio_returns=portfolio_returns,
        )
        if allowed:
            orders.append(order)
            # 更新可用現金（避免超額下單）
            cash -= shares * price * (1 + COMMISSION_RATE)
        else:
            logger.debug(f"  {stock_id} 買單被拒: {reason}")

    return orders


def _calc_dynamic_slippage(shares: int, avg_volume: float) -> float:
    """計算動態滑價（Kyle lambda 模型）"""
    if avg_volume > 0:
        participation = shares / avg_volume
        impact = participation * IMPACT_COEFF
        return BASE_SLIPPAGE + impact
    return BASE_SLIPPAGE


def _execute_orders(
    orders: list[dict],
    holdings: pd.DataFrame,
    cash: float,
    price_cache: dict[str, pd.DataFrame],
    trade_date: str,
) -> tuple[list[dict], pd.DataFrame, float]:
    """模擬執行訂單

    Returns: (executed_trades, updated_holdings, updated_cash)
    """
    executed: list[dict] = []
    # 轉成可變的 dict 格式方便操作
    holding_map: dict[str, dict] = {}
    if not holdings.empty:
        for _, row in holdings.iterrows():
            holding_map[row["stock_id"]] = row.to_dict()

    for order in orders:
        stock_id = order["stock_id"]
        side = order["side"]
        shares = order["shares"]
        price = order["price"]

        # 動態滑價
        pdf = price_cache.get(stock_id, pd.DataFrame())
        avg_vol = pdf["volume"].tail(20).mean() if not pdf.empty else 0
        slippage_pct = _calc_dynamic_slippage(shares, avg_vol)

        if side == "buy":
            exec_price = price * (1 + slippage_pct)
            commission = exec_price * shares * COMMISSION_RATE
            amount = exec_price * shares + commission

            if amount > cash:
                logger.debug(f"  {stock_id} 買單跳過：現金不足")
                continue

            cash -= amount

            holding_map[stock_id] = {
                "stock_id": stock_id,
                "shares": shares,
                "entry_price": exec_price,
                "entry_date": trade_date,
                "current_price": price,
                "strategy_name": order.get("strategy_name"),
            }

            executed.append({
                "trade_date": trade_date,
                "stock_id": stock_id,
                "side": "buy",
                "shares": shares,
                "price": round(exec_price, 2),
                "amount": round(amount, 0),
                "commission": round(commission, 0),
                "tax": 0,
                "slippage_pct": round(slippage_pct, 6),
                "strategy_name": order.get("strategy_name"),
                "reason": order.get("reason", "signal"),
                "realized_pnl": None,
                "realized_pnl_pct": None,
                "holding_days": None,
            })

        elif side == "sell":
            exec_price = price * (1 - slippage_pct)
            commission = exec_price * shares * COMMISSION_RATE
            tax = exec_price * shares * SELL_TAX_RATE
            proceeds = exec_price * shares - commission - tax

            cash += proceeds

            # 計算已實現損益
            holding = holding_map.get(stock_id, {})
            entry_price = holding.get("entry_price", price)
            entry_date = holding.get("entry_date")
            cost = entry_price * shares * (1 + COMMISSION_RATE)
            realized_pnl = proceeds - cost
            realized_pnl_pct = realized_pnl / cost if cost > 0 else 0.0

            holding_days = None
            if entry_date:
                try:
                    ed = pd.to_datetime(entry_date)
                    td = pd.to_datetime(trade_date)
                    holding_days = (td - ed).days
                except Exception:
                    pass

            # 移除持倉
            sell_shares = shares
            remaining = holding.get("shares", 0) - sell_shares
            if remaining <= 0:
                holding_map.pop(stock_id, None)
            else:
                holding_map[stock_id]["shares"] = remaining

            executed.append({
                "trade_date": trade_date,
                "stock_id": stock_id,
                "side": "sell",
                "shares": shares,
                "price": round(exec_price, 2),
                "amount": round(proceeds, 0),
                "commission": round(commission, 0),
                "tax": round(tax, 0),
                "slippage_pct": round(slippage_pct, 6),
                "strategy_name": order.get("strategy_name"),
                "reason": order.get("reason", "signal"),
                "realized_pnl": round(realized_pnl, 0),
                "realized_pnl_pct": round(realized_pnl_pct, 4),
                "holding_days": holding_days,
            })

    # 重建 holdings DataFrame
    if holding_map:
        updated_holdings = pd.DataFrame(list(holding_map.values()))
    else:
        updated_holdings = pd.DataFrame(
            columns=["stock_id", "shares", "entry_price", "entry_date",
                     "current_price", "strategy_name"]
        )

    return executed, updated_holdings, cash


# ===================================================================
# DB 讀寫
# ===================================================================

def _load_current_portfolio(
    initial_capital: float,
) -> tuple[pd.DataFrame, float, float]:
    """載入當前 Paper Portfolio

    Returns: (holdings_df, cash, initial_capital_from_db)
    """
    try:
        # 取最新一天的持倉
        pnl_df = safe_read_sql(
            "SELECT * FROM paper_daily_pnl ORDER BY trade_date DESC LIMIT 1"
        )
        if pnl_df.empty:
            logger.info("首次執行 Paper Trading，初始化空組合")
            return pd.DataFrame(), initial_capital, initial_capital

        latest_date = str(pnl_df["trade_date"].iloc[0])[:10]
        cash = float(pnl_df["cash"].iloc[0])

        holdings = safe_read_sql(
            "SELECT * FROM paper_portfolio WHERE trade_date = %(d)s",
            params={"d": latest_date},
        )
        logger.info(
            f"載入持倉：{len(holdings)} 檔，現金 {cash:,.0f}，"
            f"日期 {latest_date}"
        )
        return holdings, cash, initial_capital
    except Exception as e:
        logger.warning(f"載入持倉失敗: {e}，使用初始值")
        return pd.DataFrame(), initial_capital, initial_capital


def _update_db(
    trades: list[dict],
    holdings: pd.DataFrame,
    cash: float,
    total_equity: float,
    initial_capital: float,
    trade_date: str,
    risk_state,
    portfolio_returns: pd.Series | None = None,
    benchmark_return: float | None = None,
) -> None:
    """寫入 3 個 DB 表"""
    from analysis.utils.risk import calc_var, calc_sharpe

    # 1. paper_trades
    if trades:
        trades_df = pd.DataFrame(trades)
        save_to_db(trades_df, "paper_trades")
        logger.info(f"  寫入 {len(trades)} 筆交易紀錄")

    # 2. paper_portfolio（快照式：該日全部持倉）
    if not holdings.empty:
        port_df = holdings.copy()
        port_df["trade_date"] = trade_date

        # 計算衍生欄位
        if "current_price" in port_df.columns and "shares" in port_df.columns:
            port_df["market_value"] = port_df["current_price"] * port_df["shares"]
            port_df["unrealized_pnl"] = (
                (port_df["current_price"] - port_df["entry_price"]) * port_df["shares"]
            )
            port_df["unrealized_pnl_pct"] = (
                port_df["current_price"] / port_df["entry_price"] - 1
            )
            total_mv = port_df["market_value"].sum()
            if total_mv > 0:
                port_df["weight_pct"] = port_df["market_value"] / (total_mv + cash)

        save_to_db(port_df, "paper_portfolio")
        logger.info(f"  寫入 {len(port_df)} 筆持倉快照")

    # 3. paper_daily_pnl
    positions_value = 0.0
    if not holdings.empty and "current_price" in holdings.columns:
        positions_value = float((holdings["current_price"] * holdings["shares"]).sum())

    # 日損益（與前一日比較）
    try:
        prev_df = safe_read_sql(
            "SELECT total_equity FROM paper_daily_pnl "
            "WHERE trade_date < %(d)s ORDER BY trade_date DESC LIMIT 1",
            params={"d": trade_date},
        )
        prev_equity = float(prev_df["total_equity"].iloc[0]) if not prev_df.empty else initial_capital
    except Exception:
        prev_equity = initial_capital

    daily_pnl = total_equity - prev_equity
    daily_pnl_pct = daily_pnl / prev_equity if prev_equity > 0 else 0.0
    cumulative_return = (total_equity / initial_capital) - 1

    # 風險指標
    var_95 = None
    sharpe = None
    if portfolio_returns is not None and len(portfolio_returns) >= 20:
        var_95 = float(calc_var(portfolio_returns, 0.95))
        sharpe = float(calc_sharpe(portfolio_returns))

    pnl_row = pd.DataFrame([{
        "trade_date": trade_date,
        "total_equity": round(total_equity, 0),
        "cash": round(cash, 0),
        "positions_value": round(positions_value, 0),
        "position_count": len(holdings) if not holdings.empty else 0,
        "daily_pnl": round(daily_pnl, 0),
        "daily_pnl_pct": round(daily_pnl_pct, 6),
        "cumulative_return": round(cumulative_return, 6),
        "peak_equity": round(risk_state.peak_equity, 0),
        "drawdown_pct": round(risk_state.current_drawdown, 6),
        "var_95": var_95,
        "sharpe_ratio": sharpe,
        "trades_today": len(trades),
        "risk_status": risk_state.risk_status_label,
        "paused_strategies": json.dumps(sorted(risk_state.paused_strategies)),
        "strategy_loss_counts": json.dumps(risk_state.strategy_loss_counts),
        "benchmark_return": benchmark_return,
    }])
    save_to_db(pnl_row, "paper_daily_pnl")
    logger.info(
        f"  每日損益：{daily_pnl:+,.0f} ({daily_pnl_pct:+.2%})，"
        f"累積報酬 {cumulative_return:.2%}，"
        f"回撤 {risk_state.current_drawdown:.2%}"
    )


def _load_portfolio_returns() -> pd.Series:
    """載入近 60 日組合日報酬率"""
    try:
        df = safe_read_sql(
            "SELECT trade_date, daily_pnl_pct FROM paper_daily_pnl "
            "ORDER BY trade_date DESC LIMIT 60"
        )
        if df.empty:
            return pd.Series(dtype=float)
        return df["daily_pnl_pct"].astype(float)
    except Exception:
        return pd.Series(dtype=float)


def _load_industry_map() -> pd.DataFrame:
    """載入產業分類"""
    try:
        return safe_read_sql("SELECT stock_id, sector, sub_industry FROM industry_classification")
    except Exception:
        return pd.DataFrame()


def _get_benchmark_return(initial_capital: float) -> float | None:
    """計算 0050 基準累積報酬"""
    try:
        df = safe_read_sql(
            "SELECT close FROM daily_price WHERE stock_id = '0050' "
            "ORDER BY date DESC LIMIT 2"
        )
        if len(df) < 2:
            return None
        # 簡易計算：只返回 None，週報再精確計算
        return None
    except Exception:
        return None


# ===================================================================
# 主引擎
# ===================================================================

def run_paper_trading(
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    force: bool = False,
) -> None:
    """Paper Trading 主入口

    Args:
        initial_capital: 初始資金（首次使用）
        force: 跳過交易日檢查
    """
    from scanners.daily_updater import is_trading_day
    from scripts.paper_risk_control import (
        RiskLimits,
        RiskState,
        generate_halve_orders,
        generate_liquidate_orders,
        update_drawdown,
        update_strategy_losses,
    )

    today = date.today()

    # Step 0: 交易日檢查
    if not force:
        is_td, reason = is_trading_day(today)
        if not is_td:
            logger.info(f"非交易日（{reason}），跳過 Paper Trading")
            return
        logger.info(f"交易日確認：{reason}")

    trade_date = today.strftime("%Y-%m-%d")
    logger.info(f"=== Paper Trading 開始 ({trade_date}) ===")

    # Step 1: 載入已篩選策略
    from scripts.strategy_tournament import get_approved_strategies
    strategies = get_approved_strategies()
    strategy_names = [name for name, _ in strategies]
    logger.info(f"使用策略：{strategy_names}")

    # Step 2: 載入當前持倉
    holdings, cash, _ = _load_current_portfolio(initial_capital)

    # Step 3: 載入市場資料
    start_date = (today - timedelta(days=LOOKBACK_TRADE_DAYS * 2)).strftime("%Y-%m-%d")
    logger.info("載入市場資料...")
    tables = _load_all_tables(start_date, trade_date)

    price_cache = _build_stock_cache(tables.get("daily_price"))
    chip_cache = _build_stock_cache(tables.get("chip_institutional"))
    per_cache = _build_stock_cache(tables.get("stock_per"))
    rev_cache = _build_stock_cache(tables.get("month_revenue"))
    extra_caches = {
        "day_trading": _build_stock_cache(tables.get("day_trading")),
        "chip_broker": _build_stock_cache(tables.get("chip_broker")),
        "chip_gov_bank": _build_stock_cache(tables.get("chip_gov_bank")),
    }

    # 更新持倉的 current_price
    if not holdings.empty:
        for idx, row in holdings.iterrows():
            sid = row["stock_id"]
            pdf = price_cache.get(sid, pd.DataFrame())
            if not pdf.empty:
                holdings.at[idx, "current_price"] = float(pdf["close"].iloc[-1])

    # 計算總資產
    positions_value = 0.0
    if not holdings.empty and "current_price" in holdings.columns:
        positions_value = float((holdings["current_price"] * holdings["shares"]).sum())
    total_equity = cash + positions_value

    # Step 4: 載入風控狀態
    risk_limits = RiskLimits(max_positions=MAX_POSITIONS)
    risk_state = RiskState(peak_equity=max(total_equity, initial_capital))

    try:
        pnl_df = safe_read_sql(
            "SELECT * FROM paper_daily_pnl ORDER BY trade_date DESC LIMIT 1"
        )
        if not pnl_df.empty:
            risk_state = RiskState.from_db_row(pnl_df.iloc[0])
    except Exception:
        pass

    # 載入組合報酬和產業分類
    portfolio_returns = _load_portfolio_returns()
    industry_map = _load_industry_map()
    ind_map_dict: dict[str, dict] = {}
    if not industry_map.empty:
        for _, row in industry_map.iterrows():
            ind_map_dict[row["stock_id"]] = {
                "sector": row.get("sector"),
                "sub_industry": row.get("sub_industry"),
            }

    # Step 5: 回撤檢查（先於訊號掃描，可能觸發減半/清倉）
    alerts = update_drawdown(total_equity, risk_state, risk_limits)
    forced_orders: list[dict] = []

    if risk_state.is_liquidated and not holdings.empty:
        logger.warning("觸發清倉熔斷！")
        forced_orders = generate_liquidate_orders(holdings)
    elif risk_state.is_halved and not holdings.empty:
        logger.warning("觸發減半熔斷！")
        forced_orders = generate_halve_orders(holdings)

    # Step 6: 掃描訊號
    logger.info("掃描全市場訊號...")
    signals = _scan_signals(
        strategies, price_cache,
        chip_cache, per_cache, rev_cache, extra_caches, ind_map_dict,
    )

    # Step 7: 構建訂單
    orders = _construct_orders(
        signals, holdings, cash, total_equity, price_cache,
        risk_state, risk_limits, industry_map, portfolio_returns,
    )

    # 加入熔斷強制訂單（優先）
    if forced_orders:
        orders = forced_orders + [o for o in orders if o["side"] == "sell"]

    # Step 8: 模擬執行
    logger.info(f"執行 {len(orders)} 筆訂單...")
    executed, updated_holdings, updated_cash = _execute_orders(
        orders, holdings, cash, price_cache, trade_date,
    )

    buy_count = sum(1 for t in executed if t["side"] == "buy")
    sell_count = sum(1 for t in executed if t["side"] == "sell")
    logger.info(f"成交：買 {buy_count} 筆、賣 {sell_count} 筆")

    # 更新持倉的 current_price
    if not updated_holdings.empty:
        for idx, row in updated_holdings.iterrows():
            sid = row["stock_id"]
            pdf = price_cache.get(sid, pd.DataFrame())
            if not pdf.empty:
                updated_holdings.at[idx, "current_price"] = float(pdf["close"].iloc[-1])

    # 重算總資產
    positions_value = 0.0
    if not updated_holdings.empty and "current_price" in updated_holdings.columns:
        positions_value = float(
            (updated_holdings["current_price"] * updated_holdings["shares"]).sum()
        )
    total_equity = updated_cash + positions_value

    # Step 9: 更新風控
    alerts += update_drawdown(total_equity, risk_state, risk_limits)
    alerts += update_strategy_losses(executed, risk_state, risk_limits)

    # Step 10: 寫入 DB
    _update_db(
        executed, updated_holdings, updated_cash, total_equity,
        initial_capital, trade_date, risk_state, portfolio_returns,
    )

    # Step 11: 報告 + 告警
    try:
        from scripts.paper_report import (
            check_and_send_alerts,
            generate_daily_report,
            send_daily_email,
        )
        report_path = generate_daily_report(trade_date)
        if report_path:
            send_daily_email(report_path)
        if alerts:
            check_and_send_alerts(alerts)
    except ImportError:
        logger.info("paper_report 模組尚未實作，跳過報告")
    except Exception as e:
        logger.warning(f"報告產生失敗: {e}")

    logger.info(
        f"=== Paper Trading 完成 ===\n"
        f"  持倉：{len(updated_holdings)} 檔\n"
        f"  現金：{updated_cash:,.0f}\n"
        f"  總資產：{total_equity:,.0f}\n"
        f"  風控狀態：{risk_state.risk_status_label}"
    )


# ===================================================================
# CLI
# ===================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Paper Trading 模擬交易")
    parser.add_argument(
        "--capital", type=float, default=DEFAULT_INITIAL_CAPITAL,
        help=f"初始資金（預設 {DEFAULT_INITIAL_CAPITAL:,.0f}）",
    )
    parser.add_argument("--force", action="store_true", help="跳過交易日檢查")
    args = parser.parse_args()
    run_paper_trading(initial_capital=args.capital, force=args.force)
