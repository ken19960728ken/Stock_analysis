"""
台灣股市量化交易系統 — 統一入口

Usage:
    python main.py --scanner price          # 日K價格資料（Yahoo Finance）
    python main.py --scanner price_weekly   # 週K價格資料（Yahoo Finance）
    python main.py --scanner price_monthly  # 月K價格資料（Yahoo Finance）
    python main.py --scanner fundamental    # 財務報表 + 股利
    python main.py --scanner chip           # 籌碼面資料
    python main.py --scanner valuation      # 月營收 + PER/PBR + 市值
    python main.py --scanner industry       # 產業分類（FinMind taiwan_stock_info）
    python main.py --scanner all            # Yahoo 先跑，再跑 FinMind（受預算控制）
    python main.py --daily                  # 手動執行今日更新（價格 + 籌碼）
    python main.py --init-index             # 從遠端 DB 初始化本地索引
    python main.py --usage                  # 查詢 FinMind API 使用量
    python main.py --scanner chip --budget 50   # 限制 FinMind API 預算
    python main.py --schedule               # 排程模式：每小時自動循環
    python main.py --show-failures          # 顯示各 dataset 失敗統計
    python main.py --reset-failures         # 清除全部失敗記錄
    python main.py --reset-failures market_value  # 清除指定 dataset 失敗記錄
    python main.py --dashboard              # 啟動監控儀表板 (http://localhost:8050)
    python main.py --analysis               # 啟動量化分析平台 (http://localhost:8501)
    python main.py --pick-stocks                          # 每日選股報告
    python main.py --pick-stocks --pick-top 10 --pick-days 7  # 自訂參數
    python main.py --report                              # 列出所有策略
    python main.py --report "MA 交叉" --report-all       # 全市場 MA 交叉回測報告
    python main.py --report "法人跟單" --report-stocks 2330 2317  # 指定股票回測報告
"""
import argparse
import os
import sys
import time
from datetime import datetime, timedelta

from core.logger import setup_logger

logger = setup_logger("main")

SCANNER_MAP = {
    "price": ("scanners.price_scanner", "PriceScanner"),
    "price_weekly": ("scanners.price_scanner_weekly", "WeeklyPriceScanner"),
    "price_monthly": ("scanners.price_scanner_monthly", "MonthlyPriceScanner"),
    "fundamental": ("scanners.fundamental_scanner", "FundamentalScanner"),
    "chip": ("scanners.chip_scanner", "ChipScanner"),
    "valuation": ("scanners.valuation_scanner", "ValuationScanner"),
    "industry": ("scanners.industry_scanner", "IndustryScanner"),
}

# 來源分流：Yahoo 不受 FinMind 配額限制
YAHOO_SCANNERS = ["price", "price_weekly", "price_monthly"]
FINMIND_SCANNERS = ["fundamental", "chip", "valuation"]
FINMIND_RUN_ORDER = ["fundamental", "chip", "valuation"]


def run_scanner(name):
    if name not in SCANNER_MAP:
        print(f"未知的 scanner: {name}")
        print(f"可用選項: {', '.join(SCANNER_MAP.keys())}")
        return

    module_path, class_name = SCANNER_MAP[name]

    import importlib
    module = importlib.import_module(module_path)
    scanner_cls = getattr(module, class_name)

    print(f"\n{'='*50}")
    print(f"啟動 {class_name}")
    print(f"{'='*50}\n")

    scanner_cls().scan()


def run_init_index():
    """從遠端 DB 初始化本地 SQLite 索引"""
    from core.local_index import close, init_from_remote
    try:
        print("正在從遠端 DB 初始化本地索引...")
        init_from_remote()
        print("本地索引初始化完成。")
    finally:
        close()


def run_usage():
    """查詢並顯示 FinMind API 使用量"""
    from core.finmind_client import get_api_usage
    user_count, api_request_limit = get_api_usage()
    if user_count is None:
        print("無法查詢 API 使用量（請確認 FINMIND_TOKEN 是否正確設定）")
        return
    remaining = api_request_limit - user_count
    print(f"FinMind API 使用量:")
    print(f"  已使用: {user_count} 次")
    print(f"  上限:   {api_request_limit} 次")
    print(f"  剩餘:   {remaining} 次")


def run_dashboard(host="0.0.0.0", port=8050):
    """啟動監控儀表板"""
    import uvicorn
    from dashboard.app import app

    logger.info(f"啟動 Dashboard: http://localhost:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


def run_analysis(port=8501):
    """啟動 Streamlit 量化分析平台"""
    import subprocess
    app_path = os.path.join(os.path.dirname(__file__), "analysis", "app.py")
    logger.info(f"啟動量化分析平台: http://localhost:{port}")
    subprocess.run([
        sys.executable, "-m", "streamlit", "run", app_path,
        "--server.port", str(port),
        "--server.headless", "true",
    ])


def run_show_failures():
    """顯示各 dataset 失敗統計"""
    from core.local_index import get_failure_summary
    summary = get_failure_summary()
    if not summary:
        print("目前沒有失敗記錄。")
        return
    print("失敗記錄統計:")
    total = 0
    for table_name, count in summary:
        print(f"  {table_name}: {count} 筆")
        total += count
    print(f"  共計: {total} 筆")


def run_reset_failures(table_name=None):
    """清除失敗記錄"""
    from core.local_index import clear_failures
    if table_name:
        clear_failures(table_name)
        print(f"已清除 {table_name} 的失敗記錄。")
    else:
        clear_failures()
        print("已清除全部失敗記錄。")


def run_schedule():
    """排程模式：每小時自動循環執行所有 scanner"""
    from core.finmind_client import get_api_usage
    from core.rate_limiter import get_budget_remaining, reset_budget, set_budget

    logger.info("排程模式啟動，每小時自動循環（Ctrl+C 可安全退出）")

    while True:
        now = datetime.now()
        logger.info(f"=== 排程週期開始: {now.strftime('%Y-%m-%d %H:%M:%S')} ===")

        # 1. Yahoo scanner 先跑（不受配額影響）
        for name in YAHOO_SCANNERS:
            run_scanner(name)

        # 2. 查詢剩餘配額
        user_count, api_request_limit = get_api_usage()
        if user_count is not None:
            remaining = api_request_limit - user_count
            logger.info(
                f"FinMind API: 已用 {user_count}/{api_request_limit}，"
                f"剩餘 {remaining} 次"
            )
            set_budget(remaining)
        else:
            logger.warning("無法查詢 API 使用量，本輪不設定預算限制")

        # 3. FinMind scanners（受預算控制）
        for name in FINMIND_RUN_ORDER:
            budget = get_budget_remaining()
            if budget is not None and budget <= 0:
                logger.info("預算已用盡，跳過剩餘 FinMind scanner")
                break
            run_scanner(name)

        # 4. 重置預算
        reset_budget()

        # 5. 計算到下個整點的秒數
        now = datetime.now()
        seconds_to_next_hour = 3600 - (now.minute * 60 + now.second)
        next_hour = now + timedelta(seconds=seconds_to_next_hour)
        logger.info(
            f"本輪完成，等待 {seconds_to_next_hour} 秒後"
            f"（約 {next_hour.strftime('%m/%d %H:%M')}）開始下一輪"
        )

        try:
            time.sleep(seconds_to_next_hour)
        except KeyboardInterrupt:
            logger.info("排程模式已安全退出")
            return


def run_daily_data():
    """執行每日資料抓取（價格 + 籌碼 + 估值面）。回傳 True 表示為交易日。"""
    from scanners.daily_updater import DailyUpdater
    is_trading_day = DailyUpdater().run()
    if not is_trading_day:
        logger.info("非交易日，跳過資料更新")
    return is_trading_day


def run_daily_report():
    """執行每日選股報告 + Email 推送。"""
    try:
        from scripts.daily_stock_picker import run_daily_pick
        logger.info("開始產出每日選股報告...")
        report_path = run_daily_pick()
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


def main():
    parser = argparse.ArgumentParser(description="台灣股市量化交易系統 — 資料撈取")
    parser.add_argument(
        "--scanner",
        choices=list(SCANNER_MAP.keys()) + ["all"],
        help="選擇要執行的 scanner (price/price_weekly/price_monthly/fundamental/chip/valuation/industry/all)",
    )
    parser.add_argument(
        "--init-index",
        action="store_true",
        help="從遠端 DB 初始化本地 SQLite 索引（首次使用或換電腦時執行）",
    )
    parser.add_argument(
        "--usage",
        action="store_true",
        help="查詢並顯示 FinMind API 使用量",
    )
    parser.add_argument(
        "--budget",
        type=int,
        metavar="N",
        help="限制本次執行最多 N 次 FinMind API call",
    )
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="排程模式：每小時自動循環執行所有 scanner",
    )
    parser.add_argument(
        "--daily",
        action="store_true",
        help="手動執行今日更新（資料抓取 + 選股報告 + Email，向後相容）",
    )
    parser.add_argument(
        "--daily-data",
        action="store_true",
        help="僅執行每日資料抓取（價格 + 籌碼 + 估值面）",
    )
    parser.add_argument(
        "--daily-report",
        action="store_true",
        help="僅執行每日選股報告 + Email 推送",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="啟動監控儀表板 (http://localhost:8050)",
    )
    parser.add_argument(
        "--analysis",
        action="store_true",
        help="啟動量化分析平台 (http://localhost:8501)",
    )
    parser.add_argument(
        "--show-failures",
        action="store_true",
        help="顯示各 dataset 失敗統計",
    )
    parser.add_argument(
        "--reset-failures",
        nargs="?",
        const="__all__",
        metavar="TABLE_NAME",
        help="清除失敗記錄（不指定表名則清除全部）",
    )
    # --- 每日選股報告 ---
    parser.add_argument(
        "--pick-stocks",
        action="store_true",
        help="執行每日選股報告",
    )
    parser.add_argument(
        "--pick-top",
        type=int,
        default=20,
        help="選股報告 Top N（預設 20）",
    )
    parser.add_argument(
        "--pick-days",
        type=int,
        default=5,
        help="考慮最近 N 天的訊號（預設 5）",
    )
    parser.add_argument(
        "--pick-date",
        type=str,
        default=None,
        help="指定選股報告日期（格式: YYYY-MM-DD，預設自動取 DB 最新日期）",
    )
    # --- 策略回測報告 ---
    parser.add_argument(
        "--report",
        nargs="?",
        const="__list__",
        metavar="STRATEGY_NAME",
        help="執行策略回測報告（不指定策略名則列出所有策略）",
    )
    parser.add_argument(
        "--report-stocks",
        nargs="+",
        metavar="STOCK_ID",
        help="報告指定股票",
    )
    parser.add_argument(
        "--report-all",
        action="store_true",
        help="報告全市場",
    )
    parser.add_argument(
        "--report-top",
        type=int,
        default=20,
        help="顯示 Top N（預設 20）",
    )
    parser.add_argument(
        "--report-years",
        type=int,
        default=3,
        help="回測年數（預設 3）",
    )
    parser.add_argument(
        "--report-param",
        nargs="+",
        metavar="KEY=VALUE",
        help="策略參數覆蓋（格式: key=value）",
    )
    args = parser.parse_args()

    # --pick-stocks：每日選股報告
    if args.pick_stocks:
        from scripts.daily_stock_picker import run_daily_pick
        run_daily_pick(top_n=args.pick_top, signal_days=args.pick_days, target_date=args.pick_date)
        return

    # --report：策略回測報告
    if args.report is not None:
        from scripts.strategy_report import parse_params, run_report
        strategy_name = None if args.report == "__list__" else args.report
        param_overrides = parse_params(args.report_param)
        run_report(
            strategy_name=strategy_name,
            stock_ids=args.report_stocks,
            all_stocks=args.report_all,
            top_n=args.report_top,
            years=args.report_years,
            param_overrides=param_overrides,
        )
        return

    # --analysis：獨立功能
    if args.analysis:
        run_analysis()
        return

    # --dashboard：獨立功能
    if args.dashboard:
        run_dashboard()
        return

    # --show-failures：獨立功能
    if args.show_failures:
        run_show_failures()
        return

    # --reset-failures：獨立功能
    if args.reset_failures is not None:
        table_name = None if args.reset_failures == "__all__" else args.reset_failures
        run_reset_failures(table_name)
        return

    # --usage：獨立功能
    if args.usage:
        run_usage()
        return

    # --init-index：獨立功能
    if args.init_index:
        run_init_index()
        return

    # --daily-data：僅執行資料抓取
    if args.daily_data:
        run_daily_data()
        return

    # --daily-report：僅執行選股報告 + Email
    if args.daily_report:
        run_daily_report()
        return

    # --daily：向後相容，資料抓取 + 選股報告
    if args.daily:
        is_trading_day = run_daily_data()
        if not is_trading_day:
            logger.info("非交易日，跳過選股報告與 Email 推送")
            return
        run_daily_report()
        return

    # --schedule 不可與 --scanner 或 --budget 同時使用
    if args.schedule:
        if args.scanner or args.budget:
            parser.error("--schedule 不可與 --scanner 或 --budget 同時使用")
        try:
            run_schedule()
        except KeyboardInterrupt:
            logger.info("排程模式已安全退出")
        return

    # 正常模式：需要 --scanner
    if not args.scanner:
        parser.error("請指定 --scanner、--daily、--usage、--schedule、--analysis 或 --init-index")

    # 設定預算（若指定）
    if args.budget is not None:
        from core.rate_limiter import set_budget
        set_budget(args.budget)

    if args.scanner == "all":
        from core.rate_limiter import get_budget_remaining
        # 1. Yahoo scanners 先跑（不受預算控制）
        for name in YAHOO_SCANNERS:
            run_scanner(name)
        # 2. FinMind scanners（受預算控制）
        for name in FINMIND_RUN_ORDER:
            budget = get_budget_remaining()
            if budget is not None and budget <= 0:
                logger.info("預算已用盡，跳過剩餘 FinMind scanner")
                break
            run_scanner(name)
    else:
        run_scanner(args.scanner)


if __name__ == "__main__":
    main()
