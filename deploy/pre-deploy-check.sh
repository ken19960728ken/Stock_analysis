#!/usr/bin/env bash
# ==============================================================================
# 部署前檢查腳本
# 驗證：Git 工作區乾淨、版本號格式、tag 不重複、測試通過、CHANGELOG 有記錄
# 用法: bash deploy/pre-deploy-check.sh
# ==============================================================================
set -euo pipefail

PASS=0
FAIL=0
WARN=0

check_pass() { echo "  ✓ $1"; ((PASS++)); }
check_fail() { echo "  ✗ $1"; ((FAIL++)); }
check_warn() { echo "  ⚠ $1"; ((WARN++)); }

echo "=== 部署前檢查 ==="
echo ""

# --- 0. 必須在 main 分支 ---
echo "[分支檢查]"
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" == "main" ]; then
    check_pass "目前在 main 分支"
else
    check_fail "只能從 main 分支部署（目前在: ${CURRENT_BRANCH}）"
fi

# --- 1. 讀取版本號 ---
if ! VERSION=$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])" 2>/dev/null); then
    check_fail "無法從 pyproject.toml 讀取版本號"
    echo ""
    echo "檢查結果: ${FAIL} 項失敗，無法繼續"
    exit 1
fi
echo "版本號: ${VERSION}"
echo ""

# --- 2. Git 工作區乾淨 ---
echo "[Git 狀態]"
if [ -z "$(git status --porcelain)" ]; then
    check_pass "Git 工作區乾淨"
else
    check_fail "Git 工作區有未提交的變更"
    git status --short
fi

# --- 3. 版本號格式（SemVer X.Y.Z） ---
echo ""
echo "[版本號格式]"
if [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    check_pass "版本號格式正確: ${VERSION}"
else
    check_fail "版本號格式不正確: ${VERSION}（應為 X.Y.Z）"
fi

# --- 4. Git tag 不重複 ---
echo ""
echo "[Git Tag]"
if [ -z "$(git tag -l "v${VERSION}")" ]; then
    check_pass "Git tag v${VERSION} 尚未存在"
else
    check_warn "Git tag v${VERSION} 已存在（重複部署同版本）"
fi

# --- 5. 測試通過 ---
echo ""
echo "[測試]"
if uv run pytest tests/ -q --tb=no 2>/dev/null; then
    check_pass "所有測試通過"
else
    check_fail "測試未通過"
fi

# --- 6. CHANGELOG 有此版本記錄 ---
echo ""
echo "[CHANGELOG]"
if [ ! -f "CHANGELOG.md" ]; then
    check_fail "CHANGELOG.md 不存在"
elif grep -q "## \[${VERSION}\]" CHANGELOG.md; then
    check_pass "CHANGELOG.md 已記錄 v${VERSION}"
else
    check_fail "CHANGELOG.md 缺少 v${VERSION} 的記錄"
fi

# --- 結果摘要 ---
echo ""
echo "========================================="
echo "檢查結果: ${PASS} 通過 / ${FAIL} 失敗 / ${WARN} 警告"
echo "========================================="

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo "部署被阻止。請修正上述失敗項後再試。"
    exit 1
else
    echo ""
    echo "所有檢查通過，可以部署。"
    exit 0
fi
