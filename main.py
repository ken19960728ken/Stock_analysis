"""
台灣股市量化交易系統 — 統一入口

Usage:
    python main.py --scanner price          # 日K價格資料（Yahoo Finance）
    python main.py --scanner fundamental    # 財務報表 + 股利
    python main.py --scanner chip           # 籌碼面資料
    python main.py --scanner valuation      # 月營收 + PER/PBR + 市值
    python main.py --scanner all            # Yahoo 先跑，再跑 FinMind（受預算控制）
    python main.py --init-index             # 從遠端 DB 初始化本地索引
    python main.py --usage                  # 查詢 FinMind API 使用量
    python main.py --scanner chip --budget 50   # 限制 FinMind API 預算
    python main.py --schedule               # 排程模式：每小時自動循環
    python main.py --show-failures          # 顯示各 dataset 失敗統計
    python main.py --reset-failures         # 清除全部失敗記錄
    python main.py --reset-failures market_value  # 清除指定 dataset 失敗記錄
    python main.py --dashboard              # 啟動監控儀表板 (http://localhost:8050)
"""
import argparse
import sys
import time
from datetime import datetime

from core.logger import setup_logger

logger = setup_logger("main")

SCANNER_MAP = {
    "price": ("scanners.price_scanner", "PriceScanner"),
    "fundamental": ("scanners.fundamental_scanner", "FundamentalScanner"),
    "chip": ("scanners.chip_scanner", "ChipScanner"),
    "valuation": ("scanners.valuation_scanner", "ValuationScanner"),
}

# 來源分流：Yahoo 不受 FinMind 配額限制
YAHOO_SCANNERS = ["price"]
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
        next_hour = now.replace(
            minute=0, second=0, microsecond=0
        ).replace(hour=now.hour + 1 if now.hour < 23 else 0)
        logger.info(
            f"本輪完成，等待 {seconds_to_next_hour} 秒後"
            f"（約 {next_hour.strftime('%H:%M')}）開始下一輪"
        )

        try:
            time.sleep(seconds_to_next_hour)
        except KeyboardInterrupt:
            logger.info("排程模式已安全退出")
            return


def main():
    parser = argparse.ArgumentParser(description="台灣股市量化交易系統 — 資料撈取")
    parser.add_argument(
        "--scanner",
        choices=list(SCANNER_MAP.keys()) + ["all"],
        help="選擇要執行的 scanner (price/fundamental/chip/valuation/all)",
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
        "--dashboard",
        action="store_true",
        help="啟動監控儀表板 (http://localhost:8050)",
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
    args = parser.parse_args()

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
        parser.error("請指定 --scanner、--usage、--schedule 或 --init-index")

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
