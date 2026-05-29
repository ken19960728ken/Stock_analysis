#!/usr/bin/env bash
# ==============================================================================
# 設定 Cloud Scheduler — 每日觸發 stock-data + stock-report 兩個 Job
#   stock-data:   18:30 台北 (30 10 * * 1-5 UTC)
#   stock-report: 18:40 台北 (40 10 * * 1-5 UTC)，延遲 10 分鐘等資料抓取完成
# 用法: bash deploy/setup-scheduler.sh
# ==============================================================================
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:?請設定 GCP_PROJECT_ID 環境變數}"
REGION="${GCP_REGION:-asia-east1}"

# 自動偵測 default compute service account（不依賴 App Engine）
SA_EMAIL=$(gcloud iam service-accounts list --project="$PROJECT_ID" \
    --filter="email:compute@developer.gserviceaccount.com" \
    --format="value(email)" | head -1)
[ -z "$SA_EMAIL" ] && { echo "ERROR: 找不到 default compute service account"; exit 1; }
echo "使用 Service Account: $SA_EMAIL"

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
        --oauth-service-account-email="$SA_EMAIL" \
        --description="$DESCRIPTION"
}

# 排程 1: 資料抓取 — 18:30 UTC+8
setup_scheduler "trigger-stock-data" "stock-data" \
    "30 10 * * 1-5" \
    "每日 18:30 台北時間觸發 stock-data Job（週一至五）"

# 排程 2: 選股報告 — 18:40 UTC+8（延遲 10 分鐘）
setup_scheduler "trigger-stock-report" "stock-report" \
    "40 10 * * 1-5" \
    "每日 18:40 台北時間觸發 stock-report Job（週一至五）"

# 排程 3: 季報增量更新 — 19:00 UTC+8（季報公布月：2/3/5/8/11 的週一至五）
setup_scheduler "trigger-stock-fundamental" "stock-fundamental" \
    "0 11 * 2,3,5,8,11 1-5" \
    "季報公布月 19:00 台北時間觸發 stock-fundamental Job（2/3/5/8/11 月，週一至五）"

# 排程 4: Paper Trading — 18:50 UTC+8（在 data + report 之後）
setup_scheduler "trigger-stock-paper-trading" "stock-paper-trading" \
    "50 10 * * 1-5" \
    "每日 18:50 台北時間觸發 stock-paper-trading Job（週一至五）"

echo "=== 完成 ==="
echo "排程:"
echo "  trigger-stock-data:          30 10 * * 1-5 UTC (= 18:30 UTC+8)"
echo "  trigger-stock-report:        40 10 * * 1-5 UTC (= 18:40 UTC+8)"
echo "  trigger-stock-paper-trading: 50 10 * * 1-5 UTC (= 18:50 UTC+8)"
echo "  trigger-stock-fundamental:   0 11 * 2,3,5,8,11 1-5 UTC (= 19:00 UTC+8，季報公布月)"
echo "手動觸發:"
echo "  gcloud scheduler jobs run trigger-stock-data --location=$REGION --project=$PROJECT_ID"
echo "  gcloud scheduler jobs run trigger-stock-report --location=$REGION --project=$PROJECT_ID"
echo "  gcloud scheduler jobs run trigger-stock-paper-trading --location=$REGION --project=$PROJECT_ID"
echo "  gcloud scheduler jobs run trigger-stock-fundamental --location=$REGION --project=$PROJECT_ID"
