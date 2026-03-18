#!/usr/bin/env bash
# ==============================================================================
# 設定 Cloud Scheduler — 每日觸發 stock-data + stock-report 兩個 Job
#   stock-data:   17:00 台北 (0 9 * * 1-5 UTC)
#   stock-report: 17:10 台北 (10 9 * * 1-5 UTC)，延遲 10 分鐘等資料抓取完成
# 用法: bash deploy/setup-scheduler.sh
# ==============================================================================
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:?請設定 GCP_PROJECT_ID 環境變數}"
REGION="${GCP_REGION:-asia-east1}"

# --- Helper: 建立或更新排程 ---
setup_scheduler() {
    local SCHEDULER_NAME="$1"
    local JOB_NAME="$2"
    local SCHEDULE="$3"
    local DESCRIPTION="$4"

    echo "=== 設定排程: $SCHEDULER_NAME ==="
    JOB_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run"

    gcloud scheduler jobs describe "$SCHEDULER_NAME" \
        --location="$REGION" --project="$PROJECT_ID" 2>/dev/null && \
        ACTION="update" || ACTION="create"

    gcloud scheduler jobs "$ACTION" http "$SCHEDULER_NAME" \
        --location="$REGION" \
        --project="$PROJECT_ID" \
        --schedule="$SCHEDULE" \
        --time-zone="UTC" \
        --uri="$JOB_URI" \
        --http-method="POST" \
        --oauth-service-account-email="${PROJECT_ID}@appspot.gserviceaccount.com" \
        --description="$DESCRIPTION"
}

# 排程 1: 資料抓取 — 17:00 UTC+8
setup_scheduler "trigger-stock-data" "stock-data" \
    "0 9 * * 1-5" \
    "每日 17:00 台北時間觸發 stock-data Job（週一至五）"

# 排程 2: 選股報告 — 17:10 UTC+8（延遲 10 分鐘）
setup_scheduler "trigger-stock-report" "stock-report" \
    "10 9 * * 1-5" \
    "每日 17:10 台北時間觸發 stock-report Job（週一至五）"

echo "=== 完成 ==="
echo "排程:"
echo "  trigger-stock-data:   0 9 * * 1-5 UTC (= 17:00 UTC+8)"
echo "  trigger-stock-report: 10 9 * * 1-5 UTC (= 17:10 UTC+8)"
echo "手動觸發:"
echo "  gcloud scheduler jobs run trigger-stock-data --location=$REGION --project=$PROJECT_ID"
echo "  gcloud scheduler jobs run trigger-stock-report --location=$REGION --project=$PROJECT_ID"
