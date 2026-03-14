#!/usr/bin/env bash
# ==============================================================================
# GCP 專案初始化 — 啟用所需 API 服務 + 建立 Artifact Registry
# 用法: bash deploy/setup.sh
# 前置: gcloud auth login && gcloud config set project YOUR_PROJECT_ID
# ==============================================================================
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:?請設定 GCP_PROJECT_ID 環境變數}"
REGION="${GCP_REGION:-asia-east1}"
REPO_NAME="${AR_REPO_NAME:-stock-analysis}"

echo "=== 啟用 GCP API ==="
gcloud services enable \
    run.googleapis.com \
    cloudscheduler.googleapis.com \
    artifactregistry.googleapis.com \
    cloudbuild.googleapis.com \
    --project "$PROJECT_ID"

echo "=== 建立 Artifact Registry ==="
gcloud artifacts repositories describe "$REPO_NAME" \
    --location="$REGION" --project="$PROJECT_ID" 2>/dev/null || \
gcloud artifacts repositories create "$REPO_NAME" \
    --repository-format=docker \
    --location="$REGION" \
    --project="$PROJECT_ID" \
    --description="Stock analysis Docker images"

echo "=== 設定 Docker 認證 ==="
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

echo "=== 完成 ==="
echo "Artifact Registry: ${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}"
