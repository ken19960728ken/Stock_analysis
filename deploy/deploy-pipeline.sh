#!/usr/bin/env bash
# ==============================================================================
# 部署 Cloud Run Job: stock-pipeline
# 用法: bash deploy/deploy-pipeline.sh
# 環境變數需設定: GCP_PROJECT_ID, SUPABASE_URL, FINMIND_TOKEN (optional),
#                EMAIL_SENDER, EMAIL_APP_PASSWORD, EMAIL_RECIPIENTS (optional)
# ==============================================================================
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:?請設定 GCP_PROJECT_ID 環境變數}"
REGION="${GCP_REGION:-asia-east1}"
REPO_NAME="${AR_REPO_NAME:-stock-analysis}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/stock-pipeline:latest"
JOB_NAME="stock-pipeline"

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

echo "=== 部署 Cloud Run Job ==="
# 建立或更新 Job
if gcloud run jobs describe "$JOB_NAME" --region="$REGION" --project="$PROJECT_ID" &>/dev/null; then
    ACTION="update"
else
    ACTION="create"
fi

gcloud run jobs "$ACTION" "$JOB_NAME" \
    --image="$IMAGE" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --memory="512Mi" \
    --cpu=1 \
    --task-timeout="3600s" \
    --max-retries=1 \
    --env-vars-file="$ENV_FILE"

echo "=== 完成 ==="
echo "手動觸發: gcloud run jobs execute $JOB_NAME --region=$REGION --project=$PROJECT_ID"
