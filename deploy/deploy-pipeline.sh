#!/usr/bin/env bash
# ==============================================================================
# 部署 Cloud Run Jobs: stock-data + stock-report
# 同一個 Docker image，不同 CMD
# 用法: bash deploy/deploy-pipeline.sh
# 環境變數需設定: GCP_PROJECT_ID, SUPABASE_URL, FINMIND_TOKEN (optional),
#                EMAIL_SENDER, EMAIL_APP_PASSWORD, EMAIL_RECIPIENTS (optional)
# ==============================================================================
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:?請設定 GCP_PROJECT_ID 環境變數}"
REGION="${GCP_REGION:-asia-east1}"
REPO_NAME="${AR_REPO_NAME:-stock-analysis}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/stock-pipeline:latest"

echo "=== 建置 Pipeline Docker 映像 (linux/amd64) ==="
docker buildx build --platform linux/amd64 -f Dockerfile.pipeline -t "$IMAGE" --push .

echo "=== 產生環境變數檔 ==="
ENV_FILE=$(mktemp /tmp/pipeline-env-XXXXXX.yaml)
trap "rm -f $ENV_FILE" EXIT

cat > "$ENV_FILE" <<EOF
SUPABASE_URL: "${SUPABASE_URL:?請設定 SUPABASE_URL}"
DB_POOL_SIZE: "3"
DB_POOL_OVERFLOW: "2"
EOF

[ -n "${FINMIND_TOKEN:-}" ] && echo "FINMIND_TOKEN: \"${FINMIND_TOKEN}\"" >> "$ENV_FILE"
[ -n "${EMAIL_SENDER:-}" ] && echo "EMAIL_SENDER: \"${EMAIL_SENDER}\"" >> "$ENV_FILE"
[ -n "${EMAIL_APP_PASSWORD:-}" ] && echo "EMAIL_APP_PASSWORD: \"${EMAIL_APP_PASSWORD}\"" >> "$ENV_FILE"
[ -n "${EMAIL_RECIPIENTS:-}" ] && echo "EMAIL_RECIPIENTS: \"${EMAIL_RECIPIENTS}\"" >> "$ENV_FILE"
[ -n "${EMAIL_PROXY:-}" ] && echo "EMAIL_PROXY: \"${EMAIL_PROXY}\"" >> "$ENV_FILE"

# --- Helper: 建立或更新 Job ---
deploy_job() {
    local JOB_NAME="$1"
    local MEMORY="$2"
    local CPU="$3"
    local TIMEOUT="$4"
    shift 4
    local CMD_ARGS=("$@")

    echo "=== 部署 Cloud Run Job: $JOB_NAME ==="
    if gcloud run jobs describe "$JOB_NAME" --region="$REGION" --project="$PROJECT_ID" &>/dev/null; then
        ACTION="update"
    else
        ACTION="create"
    fi

    gcloud run jobs "$ACTION" "$JOB_NAME" \
        --image="$IMAGE" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --memory="$MEMORY" \
        --cpu="$CPU" \
        --task-timeout="$TIMEOUT" \
        --max-retries=1 \
        --env-vars-file="$ENV_FILE" \
        --command="uv" \
        --args="run,python,main.py,${CMD_ARGS[*]}"
}

# Job 1: stock-data — 資料抓取（價格 + 籌碼 + 估值面）
deploy_job "stock-data" "1Gi" "1" "600s" "--daily-data"

# Job 2: stock-report — 選股報告 + Email 推送
deploy_job "stock-report" "2Gi" "2" "1800s" "--daily-report"

echo "=== 完成 ==="
echo "手動觸發:"
echo "  gcloud run jobs execute stock-data --region=$REGION --project=$PROJECT_ID"
echo "  gcloud run jobs execute stock-report --region=$REGION --project=$PROJECT_ID"
