#!/usr/bin/env bash
# ==============================================================================
# 部署 Cloud Run Jobs: stock-data + stock-report
# 同一個 Docker image，不同 CMD
# 敏感變數由 Secret Manager 注入，非敏感變數由 YAML 環境變數檔傳入
# 用法: bash deploy/deploy-pipeline.sh
# 前置: bash deploy/setup-secrets.sh（建立 secrets + 授權）
# ==============================================================================
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:?請設定 GCP_PROJECT_ID 環境變數}"
REGION="${GCP_REGION:-asia-east1}"
REPO_NAME="${AR_REPO_NAME:-stock-analysis}"
IMAGE_BASE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/stock-pipeline"

# 從 pyproject.toml 讀取版本號
VERSION=$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
GIT_SHA=$(git rev-parse --short HEAD)
IMAGE_TAG="${VERSION}-${GIT_SHA}"

echo "=== 建置 Pipeline Docker 映像 (linux/amd64) ==="
echo "版本: ${VERSION} | Git SHA: ${GIT_SHA} | 標籤: ${IMAGE_TAG}"
docker buildx build --platform linux/amd64 -f Dockerfile.pipeline \
    -t "${IMAGE_BASE}:${IMAGE_TAG}" \
    -t "${IMAGE_BASE}:latest" \
    --push .

IMAGE="${IMAGE_BASE}:${IMAGE_TAG}"

echo "=== 產生環境變數檔（僅非敏感值） ==="
ENV_FILE=$(mktemp /tmp/pipeline-env-XXXXXX.yaml)
trap "rm -f $ENV_FILE" EXIT

cat > "$ENV_FILE" <<EOF
DB_POOL_SIZE: "3"
DB_POOL_OVERFLOW: "2"
EOF

[ -n "${EMAIL_SENDER:-}" ] && echo "EMAIL_SENDER: \"${EMAIL_SENDER}\"" >> "$ENV_FILE"
[ -n "${EMAIL_RECIPIENTS:-}" ] && echo "EMAIL_RECIPIENTS: \"${EMAIL_RECIPIENTS}\"" >> "$ENV_FILE"
# 敏感值（SUPABASE_URL, FINMIND_TOKEN, EMAIL_APP_PASSWORD）由 Secret Manager 注入

# --- Helper: 建立或更新 Job ---
deploy_job() {
    local JOB_NAME="$1"
    local MEMORY="$2"
    local CPU="$3"
    local TIMEOUT="$4"
    local SECRETS="$5"
    shift 5
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
        --set-secrets="$SECRETS" \
        --command="uv" \
        --args="run,python,main.py,${CMD_ARGS[*]}"
}

# Job 1: stock-data — 資料抓取（價格 + 籌碼 + 估值面）
deploy_job "stock-data" "1Gi" "1" "600s" \
    "SUPABASE_URL=supabase-url:latest,FINMIND_TOKEN=finmind-token:latest" \
    "--daily-data"

# Job 2: stock-report — 選股報告 + Email 推送
deploy_job "stock-report" "2Gi" "2" "1800s" \
    "SUPABASE_URL=supabase-url:latest,FINMIND_TOKEN=finmind-token:latest,EMAIL_APP_PASSWORD=email-app-password:latest" \
    "--daily-report"

# Job 3: stock-fundamental — 季報增量更新
deploy_job "stock-fundamental" "1Gi" "1" "7200s" \
    "SUPABASE_URL=supabase-url:latest,FINMIND_TOKEN=finmind-token:latest" \
    "--daily-fundamental"

echo "=== 完成 ==="
echo "版本: ${VERSION} | 映像標籤: ${IMAGE_TAG}"
echo "手動觸發:"
echo "  gcloud run jobs execute stock-data --region=$REGION --project=$PROJECT_ID"
echo "  gcloud run jobs execute stock-report --region=$REGION --project=$PROJECT_ID"
echo "  gcloud run jobs execute stock-fundamental --region=$REGION --project=$PROJECT_ID"
echo "回滾方式:"
echo "  gcloud run jobs update stock-data --image=${IMAGE_BASE}:<舊版標籤> --region=$REGION --project=$PROJECT_ID"
