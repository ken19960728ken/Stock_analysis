"""出場規則回測 harness — 在全市場長期歷史上掃描「選法 × 出場規則」

進場代理：複用每日選股器的 11 策略加權投票，但**時間序列化**——
對每一天 t 計算 recent_score（各策略近 N 日訊號和）→ 加權 total_score 與 agree_count，
composite_signal[t] = 1 if (agree_count[t] >= min_agree and total_score[t] > 0)。
這與 daily_stock_picker 的進場條件（agree>=2 且 total_score>0）一致，只是逐日評估。

出場：注入 ExitRule（B 時間停損 / C 停利停損 / B+C / D 出場投票）由
MultiStockBacktester 模擬，對比 0050 買入持有，輸出排序 CSV/HTML。

效能設計（維持「快」）：
  - 每檔的 11 策略 generate_signals 只算一次（昂貴），快取為 per-strategy 訊號矩陣
  - 不同 min_agree 只重算 rolling 聚合（便宜）
  - 不同 (top_k, weighting, exit_rule) 只重跑模擬迴圈（MultiStockBacktester 已 O(1) 查詢）

用法:
    uv run python scripts/exit_rule_backtest.py --stocks 2330 2317 2454 --years 3
    uv run python scripts/exit_rule_backtest.py --years 3 --universe-top 200
    uv run python scripts/exit_rule_backtest.py --quick          # 粗掃 smoke
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analysis.strategies import STRATEGY_MAP
from analysis.strategies.base import Strategy
from analysis.utils.exit_rules import (
    CompositeExit,
    ExitRule,
    PriceStopExit,
    StrategyVoteExit,
    TimeStopExit,
)
from analysis.utils.multi_stock_backtester import MultiStockBacktester
from core.db import get_engine, safe_read_sql
from core.logger import setup_logger
from scripts.daily_stock_picker import (
    MIN_AVG_VOLUME,
    STRATEGY_WEIGHTS,
    _build_stock_cache,
    _enrich_from_cache,
    _load_all_tables,
    load_all_stock_ids,
    load_industry_map,
)
from scripts.strategy_report import calc_benchmark_buyhold

logger = setup_logger("exit_rule_backtest")

DEFAULT_SIGNAL_DAYS = 5
_WEIGHT_SERIES = pd.Series(STRATEGY_WEIGHTS)


class _PassthroughStrategy(Strategy):
    """訊號已預先算好，直接回傳（讓 MultiStockBacktester 沿用已聚合的 composite 訊號）。"""

    name = "PickerComposite"
    params: dict = {}

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        return data


# ---------------------------------------------------------------------------
# 進場代理：逐日重建選股器加權投票
# ---------------------------------------------------------------------------

def _compute_stock_panel(
    stock_id: str,
    price_df: pd.DataFrame,
    strategies: dict,
    chip_cache: dict,
    per_cache: dict,
    rev_cache: dict,
    ind_map: dict,
) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """回傳 (base OHLCV, 各策略每日訊號矩陣)。11 策略只各跑一次。"""
    if price_df is None or price_df.empty or len(price_df) < 30:
        return None
    df = price_df.sort_values("date").reset_index(drop=True).copy()
    if not pd.api.types.is_datetime64_any_dtype(df["date"]):
        df["date"] = pd.to_datetime(df["date"])
    base = df[["date", "open", "high", "low", "close", "volume"]].copy()

    sig: dict[str, np.ndarray] = {}
    for name, strat in strategies.items():
        try:
            enriched = _enrich_from_cache(
                df.copy(), stock_id, name, chip_cache, per_cache, rev_cache, ind_map
            )
            res = strat.generate_signals(enriched)
            s = pd.Series(res["signal"].values, index=pd.to_datetime(res["date"]))
            aligned = s.reindex(base["date"]).fillna(0).astype(int).to_numpy()
        except Exception as e:  # noqa: BLE001 — 單檔失敗不應中斷全市場掃描
            logger.warning(f"{stock_id}/{name} 訊號失敗: {type(e).__name__}: {e}")
            aligned = np.zeros(len(base), dtype=int)
        sig[name] = aligned

    return base, pd.DataFrame(sig, index=base.index)


def _build_composite(
    base: pd.DataFrame, sigmat: pd.DataFrame, signal_days: int, min_agree: int
) -> pd.DataFrame:
    """聚合成 composite 進場訊號 + 加權分數 + 出場投票數。"""
    recent = sigmat.rolling(signal_days, min_periods=1).sum()
    w = _WEIGHT_SERIES.reindex(sigmat.columns).fillna(0.5)
    total_score = recent.mul(w, axis=1).sum(axis=1)
    agree = (recent > 0).sum(axis=1)
    neg_votes = (sigmat == -1).sum(axis=1)

    out = base.copy()
    out["_score"] = total_score.to_numpy()
    out["_neg_votes"] = neg_votes.to_numpy().astype(int)
    out["signal"] = ((agree >= min_agree) & (total_score > 0)).astype(int).to_numpy()
    return out


# ---------------------------------------------------------------------------
# 參數網格
# ---------------------------------------------------------------------------

def build_exit_grid(quick: bool) -> list[tuple[str, ExitRule]]:
    rules: list[tuple[str, ExitRule]] = []
    # B：固定持有交易日
    for n in ([10, 20] if quick else [5, 10, 20, 40, 60]):
        rules.append((f"B_time{n}", TimeStopExit(max_hold_days=n)))
    # C：停損 × 停利
    sls = [0.08] if quick else [0.05, 0.08, 0.12]
    tps = [0.15, None] if quick else [0.10, 0.15, 0.25, None]
    for sl in sls:
        for tp in tps:
            tp_lbl = "inf" if tp is None else int(tp * 100)
            rules.append((
                f"C_sl{int(sl * 100)}_tp{tp_lbl}",
                PriceStopExit(stop_loss_pct=sl, take_profit_pct=tp),
            ))
    # C：ATR 移動停損
    for m in ([] if quick else [2.0, 3.0]):
        rules.append((f"C_atr{m}", PriceStopExit(atr_trailing_mult=m)))
    # B+C：時間 + 停損/停利（先觸發者先出）
    for n in ([20] if quick else [10, 20, 40]):
        for sl in ([0.08] if quick else [0.08, 0.12]):
            rules.append((
                f"BC_t{n}_sl{int(sl * 100)}",
                CompositeExit(rules=(
                    TimeStopExit(max_hold_days=n),
                    PriceStopExit(stop_loss_pct=sl, take_profit_pct=0.15),
                )),
            ))
    # D：多策略出場投票
    for k in ([2] if quick else [1, 2, 3]):
        rules.append((f"D_vote{k}", StrategyVoteExit(k=k)))
    return rules


def build_selection_grid(quick: bool) -> tuple[list[int], list[str], list[int]]:
    top_ks = [10] if quick else [5, 10, 15, 20]
    weightings = ["equal"] if quick else ["equal", "score"]
    min_agrees = [2] if quick else [2, 3, 4]
    return top_ks, weightings, min_agrees


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def _resolve_dates(years: int) -> tuple[str, str]:
    mx = safe_read_sql("SELECT MAX(date) AS d FROM daily_price")
    end = pd.to_datetime(mx["d"].iloc[0]) if not mx.empty and mx["d"].iloc[0] else datetime.now()
    start = end - timedelta(days=int(years * 365) + 5)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _select_universe(price_cache: dict, valid_ids: set, universe_top: int) -> list[str]:
    """從合法個股中依近 20 日均量挑流動性最高的 N 檔。"""
    liq: list[tuple[str, float]] = []
    for sid, df in price_cache.items():
        if sid not in valid_ids or df is None or df.empty or "volume" not in df:
            continue
        vol = df["volume"].tail(20).mean()
        if pd.notna(vol) and vol >= MIN_AVG_VOLUME * 1000:
            liq.append((sid, float(vol)))
    liq.sort(key=lambda x: x[1], reverse=True)
    return [sid for sid, _ in liq[:universe_top]]


def run_sweep(
    stocks: list[str] | None,
    years: int,
    universe_top: int,
    quick: bool,
    signal_days: int,
    output_dir: str,
    write_html: bool,
) -> pd.DataFrame:
    engine = get_engine()
    start_date, end_date = _resolve_dates(years)
    logger.info(f"回測區間 {start_date} ~ {end_date}")

    logger.info("載入全市場資料（分段查詢）…")
    tables = _load_all_tables(start_date, end_date)
    price_cache = _build_stock_cache(tables.get("daily_price"))
    chip_cache = _build_stock_cache(tables.get("chip_institutional"))
    per_cache = _build_stock_cache(tables.get("stock_per"))
    rev_cache = _build_stock_cache(tables.get("month_revenue"))
    ind_map = load_industry_map()

    valid_ids = set(load_all_stock_ids(engine))
    if stocks:
        universe = [s for s in stocks if s in price_cache]
    else:
        universe = _select_universe(price_cache, valid_ids, universe_top)
    logger.info(f"回測標的數：{len(universe)}")
    if not universe:
        logger.error("無可回測標的")
        return pd.DataFrame()

    strategies = {name: STRATEGY_MAP[name]() for name in STRATEGY_WEIGHTS}

    # 預計算每檔的策略訊號矩陣（昂貴，只做一次）
    logger.info("預計算各檔 11 策略訊號矩陣…")
    panels: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    for i, sid in enumerate(universe, 1):
        panel = _compute_stock_panel(
            sid, price_cache.get(sid), strategies,
            chip_cache, per_cache, rev_cache, ind_map,
        )
        if panel is not None:
            panels[sid] = panel
        if i % 25 == 0:
            logger.info(f"  …{i}/{len(universe)}")
    logger.info(f"有效標的 {len(panels)} 檔")

    bench = calc_benchmark_buyhold(engine, start_date)
    bench_annual = bench["annual_return"] if bench else 0.0

    top_ks, weightings, min_agrees = build_selection_grid(quick)
    exit_grid = build_exit_grid(quick)
    total_combos = len(min_agrees) * len(top_ks) * len(weightings) * len(exit_grid)
    logger.info(f"掃描組合數：{total_combos}")

    rows: list[dict] = []
    done = 0
    for min_agree in min_agrees:
        stock_data = {
            sid: _build_composite(base, sigmat, signal_days, min_agree)
            for sid, (base, sigmat) in panels.items()
        }
        for top_k in top_ks:
            for weighting in weightings:
                for label, rule in exit_grid:
                    bt = MultiStockBacktester(
                        strategy=_PassthroughStrategy(),
                        max_positions=top_k,
                        position_sizing=weighting,
                        min_avg_volume=MIN_AVG_VOLUME * 1000,
                        exit_rule=rule,
                    )
                    r = bt.run(stock_data)
                    rows.append({
                        "min_agree": min_agree,
                        "top_k": top_k,
                        "weighting": weighting,
                        "exit": label,
                        "sharpe": r.sharpe_ratio,
                        "total_return": round(r.total_return, 4),
                        "annual_return": round(r.annual_return, 4),
                        "vs_0050": round(r.annual_return - bench_annual, 4),
                        "max_drawdown": round(r.max_drawdown, 4),
                        "win_rate": round(r.win_rate, 4),
                        "avg_hold_days": r.avg_holding_days,
                        "turnover": r.turnover_rate,
                        "trades": r.trade_count,
                        "avg_positions": r.avg_concurrent_positions,
                    })
                    done += 1
                    if done % 20 == 0:
                        logger.info(f"  進度 {done}/{total_combos}")

    result = pd.DataFrame(rows).sort_values("sharpe", ascending=False).reset_index(drop=True)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = end_date
    csv_path = out_dir / f"exit_rule_sweep_{stamp}.csv"
    result.to_csv(csv_path, index=False, encoding="utf-8-sig")
    logger.info(f"已輸出 {csv_path}")

    if write_html:
        html_path = out_dir / f"exit_rule_sweep_{stamp}.html"
        _write_html(result, bench, html_path, start_date, end_date, len(panels))
        logger.info(f"已輸出 {html_path}")

    # 主控台摘要
    print(f"\n=== 出場規則掃描 Top 10（依 Sharpe）｜0050 年化 {bench_annual:+.2%} ===")
    print(result.head(10).to_string(index=False))
    return result


def _write_html(result, bench, path, start_date, end_date, n_stocks):
    bench_line = (
        f"0050 買入持有：年化 {bench['annual_return']:+.2%}，"
        f"總報酬 {bench['total_return']:+.2%}，"
        f"最大回撤 {bench['max_drawdown']:.2%}，Sharpe {bench['sharpe_ratio']}"
        if bench else "0050 基準不可用"
    )
    table_html = result.to_html(index=False, border=0, classes="sweep")
    html = f"""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<title>出場規則掃描 {end_date}</title>
<style>
body{{font-family:-apple-system,'PingFang TC',sans-serif;margin:24px;color:#1a1a1a}}
h1{{font-size:20px}} .meta{{color:#555;margin-bottom:12px}}
table.sweep{{border-collapse:collapse;font-size:13px}}
table.sweep th,table.sweep td{{padding:4px 8px;border-bottom:1px solid #eee;text-align:right}}
table.sweep th{{background:#f5f5f7;position:sticky;top:0}}
table.sweep tr:nth-child(-n+4) td{{background:#fff7e6}}
</style></head><body>
<h1>出場規則掃描（選法 × 出場規則）</h1>
<div class="meta">區間 {start_date} ~ {end_date}｜標的 {n_stocks} 檔｜{bench_line}<br>
依 Sharpe 排序，前 4 列以底色標示。</div>
{table_html}
</body></html>"""
    path.write_text(html, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="出場規則回測掃描")
    parser.add_argument("--stocks", nargs="*", help="指定股票代碼（預設取流動性前 N 檔）")
    parser.add_argument("--years", type=int, default=3, help="回測年數（預設 3）")
    parser.add_argument("--universe-top", type=int, default=200, help="自動選股的流動性前 N 檔")
    parser.add_argument("--signal-days", type=int, default=DEFAULT_SIGNAL_DAYS)
    parser.add_argument("--quick", action="store_true", help="粗掃（小網格，smoke 用）")
    parser.add_argument("--no-html", action="store_true")
    parser.add_argument("--output", default=str(PROJECT_ROOT / "reports"))
    args = parser.parse_args()

    run_sweep(
        stocks=args.stocks,
        years=args.years,
        universe_top=args.universe_top,
        quick=args.quick,
        signal_days=args.signal_days,
        output_dir=args.output,
        write_html=not args.no_html,
    )


if __name__ == "__main__":
    main()
