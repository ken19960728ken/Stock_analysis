"""
台灣股市量化交易系統 — 統一入口

Usage:
    python main.py --scanner price          # 日K價格資料
    python main.py --scanner fundamental    # 財務報表 + 股利
    python main.py --scanner chip           # 籌碼面資料
    python main.py --scanner valuation      # 月營收 + PER/PBR + 市值
    python main.py --scanner all            # 依序執行全部
"""
import argparse
import sys


SCANNER_MAP = {
    "price": ("scanners.price_scanner", "PriceScanner"),
    "fundamental": ("scanners.fundamental_scanner", "FundamentalScanner"),
    "chip": ("scanners.chip_scanner", "ChipScanner"),
    "valuation": ("scanners.valuation_scanner", "ValuationScanner"),
}

RUN_ORDER = ["price", "fundamental", "chip", "valuation"]


def run_scanner(name):
    if name not in SCANNER_MAP:
        print(f"❌ 未知的 scanner: {name}")
        print(f"可用選項: {', '.join(SCANNER_MAP.keys())}")
        return

    module_path, class_name = SCANNER_MAP[name]

    import importlib
    module = importlib.import_module(module_path)
    scanner_cls = getattr(module, class_name)

    print(f"\n{'='*50}")
    print(f"🚀 啟動 {class_name}")
    print(f"{'='*50}\n")

    scanner_cls().scan()


def main():
    parser = argparse.ArgumentParser(description="台灣股市量化交易系統 — 資料撈取")
    parser.add_argument(
        "--scanner",
        choices=list(SCANNER_MAP.keys()) + ["all"],
        required=True,
        help="選擇要執行的 scanner (price/fundamental/chip/valuation/all)",
    )
    args = parser.parse_args()

    if args.scanner == "all":
        for name in RUN_ORDER:
            run_scanner(name)
    else:
        run_scanner(args.scanner)


if __name__ == "__main__":
    main()
