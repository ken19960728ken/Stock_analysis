#!/usr/bin/env bash
# ==============================================================================
# 一站式版本發布腳本
# 流程：pre-deploy-check → git tag → push tag → 部署 → 摘要
# 用法: bash deploy/release.sh [pipeline|analysis|both]
# 預設: both（同時部署 Pipeline 和 Analysis）
# ==============================================================================
set -euo pipefail

# --- Branch guard: 只能從 main 分支執行 ---
if [ "$(git branch --show-current)" != "main" ]; then
    echo "❌ 只能從 main 分支執行 release"
    echo ""
    echo "正確流程："
    echo "  1. git checkout main"
    echo "  2. git merge develop"
    echo "  3. bash deploy/release.sh $1"
    exit 1
fi

TARGET="${1:-both}"

if [[ "$TARGET" != "pipeline" && "$TARGET" != "analysis" && "$TARGET" != "both" ]]; then
    echo "用法: bash deploy/release.sh [pipeline|analysis|both]"
    echo "  pipeline  — 只部署 Pipeline Jobs (stock-data + stock-report)"
    echo "  analysis  — 只部署 Analysis Service (Streamlit)"
    echo "  both      — 同時部署 Pipeline + Analysis（預設）"
    exit 1
fi

# --- 1. 執行部署前檢查 ---
echo "=== Step 1: 部署前檢查 ==="
bash deploy/pre-deploy-check.sh
echo ""

# --- 2. 讀取版本號 ---
VERSION=$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
GIT_SHA=$(git rev-parse --short HEAD)

# --- 3. 建立 Git tag ---
echo "=== Step 2: 建立 Git Tag ==="
if [ -z "$(git tag -l "v${VERSION}")" ]; then
    git tag -a "v${VERSION}" -m "Release v${VERSION}"
    echo "已建立 tag: v${VERSION}"
else
    echo "tag v${VERSION} 已存在，跳過建立"
fi

# --- 4. Push tag 到遠端 ---
echo ""
echo "=== Step 3: Push Tag 到遠端 ==="
git push origin "v${VERSION}" 2>/dev/null || echo "tag 已在遠端或無遠端設定，跳過"
echo ""

# --- 5. 執行部署 ---
echo "=== Step 4: 部署 (target: ${TARGET}) ==="

if [[ "$TARGET" == "pipeline" || "$TARGET" == "both" ]]; then
    echo ""
    echo "--- 部署 Pipeline ---"
    bash deploy/deploy-pipeline.sh
fi

if [[ "$TARGET" == "analysis" || "$TARGET" == "both" ]]; then
    echo ""
    echo "--- 部署 Analysis ---"
    bash deploy/deploy-analysis.sh
fi

# --- 6. 部署摘要 ---
echo ""
echo "========================================="
echo "  發布完成"
echo "========================================="
echo "  版本:     v${VERSION}"
echo "  Git SHA:  ${GIT_SHA}"
echo "  映像標籤: ${VERSION}-${GIT_SHA}"
echo "  部署目標: ${TARGET}"
echo ""
echo "  回滾指令:"
echo "    gcloud run jobs update stock-data --image=<舊版映像> --region=\${GCP_REGION}"
echo "    gcloud run deploy stock-analysis --image=<舊版映像> --region=\${GCP_REGION}"
echo "========================================="
