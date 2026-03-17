"""
資料庫完整性掃描腳本
掃描 2026/2/23 ~ 2026/3/13 期間的資料完整性：
1. 交易日清單
2. 每日記錄數（缺漏偵測）
3. 重複資料偵測
4. 跨表一致性比較
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db import safe_read_sql

START_DATE = "2026-02-23"
END_DATE = "2026-03-13"

# 日頻表（simple 2-col key: stock_id, date）
DAILY_TABLES_SIMPLE = [
    "daily_price",
    "chip_institutional",
    "chip_margin",
    "chip_shareholding",
    "chip_short_sale",
    "stock_per",
    "market_value",
]

# 日頻表（multi-col key）
DAILY_TABLES_MULTI = {
    "chip_holding_pct": '"HoldingSharesLevel"',
    "chip_securities_lending": "transaction_type",
}


def step1_trading_days():
    """Step 1: 確定交易日清單"""
    print("=" * 60)
    print("Step 1: 交易日清單")
    print("=" * 60)

    df = safe_read_sql(
        "SELECT DISTINCT date FROM daily_price "
        "WHERE date >= :start AND date <= :end ORDER BY date",
        params={"start": START_DATE, "end": END_DATE},
    )
    trading_days = df["date"].tolist()
    print(f"交易日數量: {len(trading_days)}")
    for d in trading_days:
        print(f"  {d}")
    print()
    return trading_days


def step2_daily_counts():
    """Step 2: 逐表檢查每日記錄數"""
    print("=" * 60)
    print("Step 2: 每日記錄數")
    print("=" * 60)

    all_tables = DAILY_TABLES_SIMPLE + list(DAILY_TABLES_MULTI.keys())
    for table in all_tables:
        df = safe_read_sql(
            f"SELECT date, COUNT(*) as cnt, COUNT(DISTINCT stock_id) as stock_cnt "
            f"FROM {table} "
            f"WHERE date >= :start AND date <= :end "
            f"GROUP BY date ORDER BY date",
            params={"start": START_DATE, "end": END_DATE},
        )
        print(f"\n--- {table} ---")
        if df.empty:
            print("  ⚠ 無任何資料！")
            continue

        # 計算中位數用於判斷異常
        median_cnt = df["cnt"].median()
        median_stock = df["stock_cnt"].median()

        for _, row in df.iterrows():
            flag = ""
            if row["stock_cnt"] < median_stock * 0.8:
                flag = " ⚠ 股票數偏低"
            if row["cnt"] < median_cnt * 0.5:
                flag = " ⚠ 記錄數異常低"
            print(f"  {row['date']}  記錄={row['cnt']:>6}  股票={row['stock_cnt']:>5}{flag}")

        print(f"  [中位數] 記錄={median_cnt:.0f}  股票={median_stock:.0f}")

    # 月頻表
    print(f"\n--- month_revenue (2026/2 月營收) ---")
    df = safe_read_sql(
        "SELECT date, COUNT(*) as cnt, COUNT(DISTINCT stock_id) as stock_cnt "
        "FROM month_revenue "
        "WHERE date >= '2026-02-01' AND date <= '2026-02-28' "
        "GROUP BY date ORDER BY date",
    )
    if df.empty:
        print("  ⚠ 2026/2 月營收無資料")
    else:
        for _, row in df.iterrows():
            print(f"  {row['date']}  記錄={row['cnt']:>6}  股票={row['stock_cnt']:>5}")

    for table in ["weekly_price", "monthly_price"]:
        print(f"\n--- {table} ---")
        df = safe_read_sql(
            f"SELECT date, COUNT(*) as cnt, COUNT(DISTINCT stock_id) as stock_cnt "
            f"FROM {table} "
            f"WHERE date >= :start AND date <= :end "
            f"GROUP BY date ORDER BY date",
            params={"start": START_DATE, "end": END_DATE},
        )
        if df.empty:
            print("  此期間無資料（正常，可能尚未產生）")
        else:
            for _, row in df.iterrows():
                print(f"  {row['date']}  記錄={row['cnt']:>6}  股票={row['stock_cnt']:>5}")
    print()


def step3_duplicates():
    """Step 3: 重複資料偵測"""
    print("=" * 60)
    print("Step 3: 重複資料偵測")
    print("=" * 60)

    total_dupes = 0

    # Simple key tables
    for table in DAILY_TABLES_SIMPLE:
        df = safe_read_sql(
            f"SELECT stock_id, date, COUNT(*) as cnt "
            f"FROM {table} "
            f"WHERE date >= :start AND date <= :end "
            f"GROUP BY stock_id, date HAVING COUNT(*) > 1 "
            f"ORDER BY cnt DESC LIMIT 20",
            params={"start": START_DATE, "end": END_DATE},
        )
        n = len(df)
        total_dupes += n
        if n > 0:
            print(f"\n⚠ {table}: {n} 組重複")
            print(df.to_string(index=False))
        else:
            print(f"✓ {table}: 無重複")

    # chip_holding_pct
    df = safe_read_sql(
        'SELECT stock_id, date, "HoldingSharesLevel", COUNT(*) as cnt '
        "FROM chip_holding_pct "
        "WHERE date >= :start AND date <= :end "
        'GROUP BY stock_id, date, "HoldingSharesLevel" HAVING COUNT(*) > 1 '
        "ORDER BY cnt DESC LIMIT 20",
        params={"start": START_DATE, "end": END_DATE},
    )
    n = len(df)
    total_dupes += n
    if n > 0:
        print(f"\n⚠ chip_holding_pct: {n} 組重複")
        print(df.to_string(index=False))
    else:
        print(f"✓ chip_holding_pct: 無重複")

    # chip_securities_lending
    df = safe_read_sql(
        "SELECT stock_id, date, transaction_type, COUNT(*) as cnt "
        "FROM chip_securities_lending "
        "WHERE date >= :start AND date <= :end "
        "GROUP BY stock_id, date, transaction_type HAVING COUNT(*) > 1 "
        "ORDER BY cnt DESC LIMIT 20",
        params={"start": START_DATE, "end": END_DATE},
    )
    n = len(df)
    total_dupes += n
    if n > 0:
        print(f"\n⚠ chip_securities_lending: {n} 組重複")
        print(df.to_string(index=False))
    else:
        print(f"✓ chip_securities_lending: 無重複")

    # month_revenue
    df = safe_read_sql(
        "SELECT stock_id, date, country, COUNT(*) as cnt "
        "FROM month_revenue "
        "WHERE date >= '2026-02-01' AND date <= '2026-03-31' "
        "GROUP BY stock_id, date, country HAVING COUNT(*) > 1 "
        "ORDER BY cnt DESC LIMIT 20",
    )
    n = len(df)
    total_dupes += n
    if n > 0:
        print(f"\n⚠ month_revenue: {n} 組重複")
        print(df.to_string(index=False))
    else:
        print(f"✓ month_revenue: 無重複")

    print(f"\n總計重複組數: {total_dupes}")
    print()


def step4_cross_table(trading_days):
    """Step 4: 跨表一致性比較"""
    print("=" * 60)
    print("Step 4: 跨表一致性比較")
    print("=" * 60)

    # 抽查 3 個日期：首日、中間、末日
    sample_dates = [trading_days[0], trading_days[len(trading_days) // 2], trading_days[-1]]
    compare_tables = ["chip_institutional", "chip_margin", "stock_per", "market_value"]

    for d in sample_dates:
        print(f"\n--- 日期: {d} ---")
        # 取 daily_price 的股票集合
        dp = safe_read_sql(
            "SELECT DISTINCT stock_id FROM daily_price WHERE date = :d",
            params={"d": str(d)},
        )
        dp_set = set(dp["stock_id"].tolist())
        print(f"  daily_price 股票數: {len(dp_set)}")

        for table in compare_tables:
            other = safe_read_sql(
                f"SELECT DISTINCT stock_id FROM {table} WHERE date = :d",
                params={"d": str(d)},
            )
            other_set = set(other["stock_id"].tolist())
            missing = dp_set - other_set
            extra = other_set - dp_set
            print(
                f"  {table:25s}  股票={len(other_set):>5}  "
                f"缺少={len(missing):>4}  多出={len(extra):>4}"
            )
    print()


def step5_summary(trading_days):
    """Step 5: 產出總結報告"""
    print("=" * 60)
    print("Step 5: 總結報告")
    print("=" * 60)
    print(f"掃描範圍: {START_DATE} ~ {END_DATE}")
    print(f"交易日數量: {len(trading_days)}")
    print("詳細結果請參考上方各步驟輸出。")
    print("=" * 60)


def main():
    print(f"資料庫完整性掃描: {START_DATE} ~ {END_DATE}")
    print()

    trading_days = step1_trading_days()
    if not trading_days:
        print("❌ 未找到任何交易日，中止掃描。")
        return

    step2_daily_counts()
    step3_duplicates()
    step4_cross_table(trading_days)
    step5_summary(trading_days)


if __name__ == "__main__":
    main()
