#!/usr/bin/env bash
# ==============================================================================
# 部署 Cloud Run Service: stock-analysis (Streamlit 前端)
# 敏感變數由 Secret Manager 注入，非敏感變數由 YAML 環境變數檔傳入
# 用法: bash deploy/deploy-analysis.sh
# 前置: bash deploy/setup-secrets.sh（建立 secrets + 授權）
# ==============================================================================
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:?請設定 GCP_PROJECT_ID 環境變數}"
REGION="${GCP_REGION:-asia-east1}"
REPO_NAME="${AR_REPO_NAME:-stock-analysis}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/stock-analysis:latest"
SERVICE_NAME="stock-analysis"

echo "=== 建置 Analysis Docker 映像 (linux/amd64) ==="
docker buildx build --platform linux/amd64 -f Dockerfile.analysis -t "$IMAGE" --push .

echo "=== 產生環境變數檔（僅非敏感值） ==="
ENV_FILE=$(mktemp /tmp/analysis-env-XXXXXX.yaml)
trap "rm -f $ENV_FILE" EXIT

cat > "$ENV_FILE" <<EOF
DB_POOL_SIZE: "3"
DB_POOL_OVERFLOW: "2"
EOF

# 敏感值（SUPABASE_URL, FRED_API_KEY）由 Secret Manager 注入

echo "=== 部署 Cloud Run Service ==="
gcloud run deploy "$SERVICE_NAME" \
    --image="$IMAGE" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --memory="1Gi" \
    --cpu=1 \
    --min-instances=0 \
    --max-instances=2 \
    --port=8501 \
    --timeout=300 \
    --allow-unauthenticated \
    --env-vars-file="$ENV_FILE" \
    --set-secrets="SUPABASE_URL=supabase-url:latest,FRED_API_KEY=fred-api-key:latest"

echo "=== 完成 ==="
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" --region="$REGION" --project="$PROJECT_ID" --format="value(status.url)")
echo "服務 URL: $SERVICE_URL"
