#!/usr/bin/env bash
# ==============================================================================
# 建立 GCP Secret Manager Secrets
# 從 .env 讀取敏感值，建立或更新 4 個 Secret，並授權 Cloud Run SA 存取
# 用法: bash deploy/setup-secrets.sh
# 前置: gcloud auth login + .env 已設定好敏感變數
# ==============================================================================
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:?請設定 GCP_PROJECT_ID 環境變數}"

echo "=== 啟用 Secret Manager API ==="
gcloud services enable secretmanager.googleapis.com --project "$PROJECT_ID"

# --- 從 .env 安全讀取敏感值 ---
ENV_FILE="${ENV_FILE_PATH:-.env}"
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: 找不到 $ENV_FILE，請確認檔案存在"
    exit 1
fi

declare -A SECRET_MAP=(
    ["supabase-url"]="SUPABASE_URL"
    ["finmind-token"]="FINMIND_TOKEN"
    ["email-app-password"]="EMAIL_APP_PASSWORD"
    ["fred-api-key"]="FRED_API_KEY"
)

# 逐行讀取 .env，安全處理含空格的值
declare -A ENV_VALS
while IFS='=' read -r key value; do
    [[ "$key" =~ ^#.*$ || -z "$key" ]] && continue
    # 移除值的前後引號（如有）
    value="${value%\"}"
    value="${value#\"}"
    ENV_VALS["$key"]="$value"
done < "$ENV_FILE"

# --- Helper: 建立或更新 Secret ---
upsert_secret() {
    local SECRET_NAME="$1"
    local SECRET_VALUE="$2"

    if [ -z "$SECRET_VALUE" ]; then
        echo "  SKIP: $SECRET_NAME（值為空，跳過）"
        return
    fi

    if gcloud secrets describe "$SECRET_NAME" --project="$PROJECT_ID" &>/dev/null; then
        # Secret 已存在，新增版本
        echo "  UPDATE: $SECRET_NAME（新增版本）"
        printf '%s' "$SECRET_VALUE" | gcloud secrets versions add "$SECRET_NAME" \
            --project="$PROJECT_ID" --data-file=-
    else
        # 建立新 Secret
        echo "  CREATE: $SECRET_NAME"
        printf '%s' "$SECRET_VALUE" | gcloud secrets create "$SECRET_NAME" \
            --project="$PROJECT_ID" \
            --replication-policy="automatic" \
            --data-file=-
    fi
}

echo "=== 建立 / 更新 Secrets ==="
for SECRET_NAME in "${!SECRET_MAP[@]}"; do
    ENV_KEY="${SECRET_MAP[$SECRET_NAME]}"
    upsert_secret "$SECRET_NAME" "${ENV_VALS[$ENV_KEY]:-}"
done

# --- 授權 Cloud Run SA 存取 Secrets ---
echo "=== 授權 Service Account ==="
SA_EMAIL=$(gcloud iam service-accounts list --project="$PROJECT_ID" \
    --filter="email:compute@developer.gserviceaccount.com" \
    --format="value(email)" | head -1)

if [ -z "$SA_EMAIL" ]; then
    echo "ERROR: 找不到 default compute service account"
    exit 1
fi

echo "  Service Account: $SA_EMAIL"

# 檢查是否已有 secretAccessor 權限，避免重複綁定
EXISTING=$(gcloud projects get-iam-policy "$PROJECT_ID" \
    --flatten="bindings[].members" \
    --filter="bindings.role=roles/secretmanager.secretAccessor AND bindings.members=serviceAccount:$SA_EMAIL" \
    --format="value(bindings.role)" 2>/dev/null || true)

if [ -n "$EXISTING" ]; then
    echo "  已有 secretmanager.secretAccessor 權限，跳過"
else
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:$SA_EMAIL" \
        --role="roles/secretmanager.secretAccessor" \
        --quiet
    echo "  已授予 secretmanager.secretAccessor 權限"
fi

echo "=== 完成 ==="
echo "驗證: gcloud secrets list --project=$PROJECT_ID"
