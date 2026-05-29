#!/usr/bin/env bash
# ==============================================================================
# 部署 Cloud Run Jobs: stock-data + stock-report + stock-fundamental
# 同一個 Docker image，不同 CMD
# 敏感變數由 Secret Manager 注入，非敏感變數由 deploy/pipeline-env.yaml 傳入
# 用法: bash deploy/deploy-pipeline.sh
# 前置: bash deploy/setup-secrets.sh（建立 secrets + 授權）
# ==============================================================================
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:?請設定 GCP_PROJECT_ID 環境變數}"
REGION="${GCP_REGION:-asia-east1}"
REPO_NAME="${AR_REPO_NAME:-stock-analysis}"
IMAGE_BASE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/stock-pipeline"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/pipeline-env.yaml"

# 檢查環境變數檔案存在
if [ ! -f "$ENV_FILE" ]; then
    echo "❌ 找不到 $ENV_FILE，請確認檔案存在"
    exit 1
fi

# 檢查必要的 Email 變數已寫在 YAML 中
if ! grep -q "EMAIL_SENDER" "$ENV_FILE" || ! grep -q "EMAIL_RECIPIENTS" "$ENV_FILE"; then
    echo "❌ $ENV_FILE 缺少 EMAIL_SENDER 或 EMAIL_RECIPIENTS，stock-report 將無法寄信"
    exit 1
fi

echo "=== 環境變數檔 ==="
cat "$ENV_FILE"
echo ""

# 從 pyproject.toml 讀取版本號
VERSION=$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
GIT_SHA=$(git rev-parse --short HEAD)
IMAGE_TAG="${VERSION}-${GIT_SHA}"

FULL_GIT_SHA=$(git rev-parse HEAD)

echo "=== 建置 Pipeline Docker 映像 (linux/amd64) ==="
echo "版本: ${VERSION} | Git SHA: ${GIT_SHA} | 標籤: ${IMAGE_TAG}"
docker buildx build --platform linux/amd64 -f Dockerfile.pipeline \
    --build-arg APP_VERSION="${VERSION}" \
    --build-arg GIT_COMMIT="${FULL_GIT_SHA}" \
    -t "${IMAGE_BASE}:${IMAGE_TAG}" \
    -t "${IMAGE_BASE}:latest" \
    --push .

IMAGE="${IMAGE_BASE}:${IMAGE_TAG}"

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

# Job 4: stock-paper-trading — Paper Trading 模擬交易
deploy_job "stock-paper-trading" "2Gi" "2" "1800s" \
    "SUPABASE_URL=supabase-url:latest,FINMIND_TOKEN=finmind-token:latest,EMAIL_APP_PASSWORD=email-app-password:latest" \
    "--paper-trading"

echo ""
echo "=== 部署完成 ==="
echo "版本: ${VERSION} | 映像標籤: ${IMAGE_TAG}"
echo "環境變數檔: ${ENV_FILE}"
echo ""
echo "手動觸發:"
echo "  gcloud run jobs execute stock-data --region=$REGION --project=$PROJECT_ID"
echo "  gcloud run jobs execute stock-report --region=$REGION --project=$PROJECT_ID"
echo "  gcloud run jobs execute stock-fundamental --region=$REGION --project=$PROJECT_ID"
echo "  gcloud run jobs execute stock-paper-trading --region=$REGION --project=$PROJECT_ID"
echo "回滾方式:"
echo "  gcloud run jobs update stock-data --image=${IMAGE_BASE}:<舊版標籤> --region=$REGION --project=$PROJECT_ID"
