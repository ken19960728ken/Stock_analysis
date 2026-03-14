#!/usr/bin/env bash
# ==============================================================================
# 設定 Cloud Scheduler — 每日 17:00 台北時間 (UTC+8) 觸發 Pipeline Job
# Cron: 0 9 * * 1-5 UTC = 17:00 台北 週一至五
# 用法: bash deploy/setup-scheduler.sh
# ==============================================================================
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:?請設定 GCP_PROJECT_ID 環境變數}"
REGION="${GCP_REGION:-asia-east1}"
JOB_NAME="stock-pipeline"
SCHEDULER_NAME="trigger-stock-pipeline"

echo "=== 設定 Cloud Scheduler ==="

# 取得 Cloud Run Job 的完整路徑
JOB_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run"

# 建立或更新排程
gcloud scheduler jobs describe "$SCHEDULER_NAME" \
    --location="$REGION" --project="$PROJECT_ID" 2>/dev/null && \
    ACTION="update" || ACTION="create"

gcloud scheduler jobs "$ACTION" http "$SCHEDULER_NAME" \
    --location="$REGION" \
    --project="$PROJECT_ID" \
    --schedule="0 9 * * 1-5" \
    --time-zone="UTC" \
    --uri="$JOB_URI" \
    --http-method="POST" \
    --oauth-service-account-email="${PROJECT_ID}@appspot.gserviceaccount.com" \
    --description="每日 17:00 台北時間觸發 stock-pipeline Job（週一至五）"

echo "=== 完成 ==="
echo "排程: 0 9 * * 1-5 UTC (= 17:00 UTC+8 週一至五)"
echo "手動觸發: gcloud scheduler jobs run $SCHEDULER_NAME --location=$REGION --project=$PROJECT_ID"
