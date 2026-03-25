#!/bin/bash
# 全量回補腳本 — 依序執行所有資料集回補
# 使用方式: nohup bash scripts/run_full_backfill.sh > logs/backfill_full.log 2>&1 &

cd /Users/wangxiangkuan/Documents/PythonCode/Stock_analysis

echo "=========================================="
echo "開始全量回補: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="

# Batch 1: cash_flows（最優先，修復 FCF 策略）
echo ""
echo "[Batch 1] cash_flows — $(date '+%H:%M:%S')"
uv run python scripts/backfill_new_datasets.py --dataset cash_flows --start 2020-01-01

# Batch 2: day_trading（2023年起，3年數據）
echo ""
echo "[Batch 2] day_trading — $(date '+%H:%M:%S')"
uv run python scripts/backfill_new_datasets.py --dataset day_trading --start 2023-01-01

# Batch 3: dividend_result（逐股）
echo ""
echo "[Batch 3] dividend_result — $(date '+%H:%M:%S')"
uv run python scripts/backfill_new_datasets.py --dataset dividend_result --start 2020-01-01

# Batch 4: Sponsor 資料集（券商分點 + 官股行庫）
echo ""
echo "[Batch 4] chip_broker — $(date '+%H:%M:%S')"
uv run python scripts/backfill_new_datasets.py --dataset chip_broker --start 2024-01-01

echo ""
echo "[Batch 5] chip_gov_bank — $(date '+%H:%M:%S')"
uv run python scripts/backfill_new_datasets.py --dataset chip_gov_bank --start 2024-01-01

# 最後建立 DB 約束
echo ""
echo "[Final] 建立 DB 約束 — $(date '+%H:%M:%S')"
uv run python scripts/db_add_constraints.py

echo ""
echo "=========================================="
echo "全量回補完成: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="
