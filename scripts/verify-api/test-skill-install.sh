#!/usr/bin/env bash
# .skill 上传（平台 zhangsan / Internal Token）+ 安装（admin Cookie）验证
#
# 用法：
#   bash scripts/verify-api/test-skill-install.sh
#   bash scripts/verify-api/test-skill-install.sh --skip-install   # 只测 zhangsan 上传
#   bash scripts/verify-api/test-skill-install.sh --admin-self       # admin 自建 thread 上传+安装（可跑通 install API）
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

SKIP_INSTALL=0
ADMIN_SELF=0
for arg in "$@"; do
  case "$arg" in
    --skip-install) SKIP_INSTALL=1 ;;
    --admin-self) ADMIN_SELF=1 ;;
  esac
done

INTERNAL_TOKEN="${DEER_FLOW_INTERNAL_AUTH_TOKEN:-X-DeerFlow-Internal-Token-valid}"
OWNER="${DEER_FLOW_OWNER_USER_ID:-zhangsan}"
GATEWAY="${DEER_FLOW_GATEWAY_URL:-http://127.0.0.1:8001}"
SKILL_DIR="${ROOT}/scripts/verify-api/invoice-test-check"
OUT_DIR="${TMPDIR:-/tmp}/deerflow-skill-pack"
STATE_FILE="${ROOT}/.deer-flow/verify-api/skill-install.state.json"
ADMIN_COOKIE="${ROOT}/.deer-flow/verify-api/admin.cookies"
ADMIN_EMAIL="${DEER_FLOW_ADMIN_EMAIL:-admin@example.com}"
ADMIN_PASSWORD="${DEER_FLOW_ADMIN_PASSWORD:-AdminPass123!}"

mkdir -p "$(dirname "$STATE_FILE")" "$OUT_DIR"

echo "== Step 0: package .skill =="
python3 scripts/verify-api/package_skill.py "$SKILL_DIR" "$OUT_DIR" >/dev/null
ARCHIVE="${OUT_DIR}/invoice-test-check.skill"
if [[ ! -f "$ARCHIVE" ]]; then
  echo "Missing archive: $ARCHIVE" >&2
  exit 1
fi
echo "Archive: $ARCHIVE ($(wc -c < "$ARCHIVE") bytes)"

_admin_login() {
  if ! curl -sS -f -X POST "${GATEWAY}/api/v1/auth/login/local" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -c "${ADMIN_COOKIE}" \
    -d "username=${ADMIN_EMAIL}&password=${ADMIN_PASSWORD}" >/dev/null 2>&1; then
    echo "Admin login failed, trying initialize..."
    curl -sS -X POST "${GATEWAY}/api/v1/auth/initialize" \
      -H "Content-Type: application/json" \
      -c "${ADMIN_COOKIE}" \
      -d "{\"email\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\"}" || true
    curl -sS -X POST "${GATEWAY}/api/v1/auth/login/local" \
      -H "Content-Type: application/x-www-form-urlencoded" \
      -c "${ADMIN_COOKIE}" \
      -d "username=${ADMIN_EMAIL}&password=${ADMIN_PASSWORD}"
  fi
  CSRF="$(grep csrf_token "${ADMIN_COOKIE}" | awk '{print $NF}')"
  if [[ -z "$CSRF" ]]; then
    echo "Admin cookie/csrf missing. Run:" >&2
    echo "  bash scripts/verify-api/verify.sh api_verify.py init-admin" >&2
    exit 1
  fi
}

if [[ "$ADMIN_SELF" -eq 1 ]]; then
  echo ""
  echo "== Mode: admin-self (admin 创建 thread + 上传 + 安装) =="
  _admin_login
  echo "Admin cookie: ${ADMIN_COOKIE}"

  THREAD_JSON="$(curl -sS -X POST "${GATEWAY}/api/threads" \
    -H "Content-Type: application/json" \
    -H "X-CSRF-Token: ${CSRF}" \
    -b "${ADMIN_COOKIE}" \
    -d '{"metadata":{"label":"skill-install-admin-self"}}')"
  echo "$THREAD_JSON"
  THREAD_ID="$(python3 -c "import json,sys; print(json.load(sys.stdin)['thread_id'])" <<< "$THREAD_JSON")"

  UPLOAD_JSON="$(curl -sS -X POST "${GATEWAY}/api/threads/${THREAD_ID}/uploads" \
    -H "X-CSRF-Token: ${CSRF}" \
    -b "${ADMIN_COOKIE}" \
    -F "files=@${ARCHIVE};type=application/octet-stream")"
  echo "$UPLOAD_JSON"
  VPATH="$(python3 -c "import json,sys; print(json.load(sys.stdin)['files'][0]['virtual_path'])" <<< "$UPLOAD_JSON")"

  INSTALL_BODY="$(curl -sS -w "\nHTTP_STATUS=%{http_code}" -X POST "${GATEWAY}/api/skills/install" \
    -H "Content-Type: application/json" \
    -H "X-CSRF-Token: ${CSRF}" \
    -b "${ADMIN_COOKIE}" \
    -d "{\"thread_id\":\"${THREAD_ID}\",\"path\":\"${VPATH}\"}")"
  echo "$INSTALL_BODY"

  echo ""
  echo "--- admin custom skills ---"
  curl -sS "${GATEWAY}/api/skills/custom" -H "X-CSRF-Token: ${CSRF}" -b "${ADMIN_COOKIE}"
  echo ""
  exit 0
fi

echo ""
echo "== Step 1: zhangsan create thread (Internal Token) =="
THREAD_JSON="$(curl -sS -X POST "${GATEWAY}/api/threads" \
  -H "Content-Type: application/json" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}" \
  -d '{"metadata":{"label":"skill-install-test"}}')"
echo "$THREAD_JSON"
THREAD_ID="$(python3 -c "import json,sys; print(json.load(sys.stdin)['thread_id'])" <<< "$THREAD_JSON")"

echo ""
echo "== Step 2: zhangsan upload .skill =="
UPLOAD_JSON="$(curl -sS -X POST "${GATEWAY}/api/threads/${THREAD_ID}/uploads" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}" \
  -F "files=@${ARCHIVE};type=application/octet-stream")"
echo "$UPLOAD_JSON"
VPATH="$(python3 -c "import json,sys; print(json.load(sys.stdin)['files'][0]['virtual_path'])" <<< "$UPLOAD_JSON")"

python3 - <<PY
import json
from pathlib import Path
state = {
    "thread_id": "${THREAD_ID}",
    "virtual_path": "${VPATH}",
    "owner": "${OWNER}",
    "archive": "${ARCHIVE}",
}
Path("${STATE_FILE}").write_text(json.dumps(state, indent=2), encoding="utf-8")
print(f"Saved state -> ${STATE_FILE}")
PY

if [[ "$SKIP_INSTALL" -eq 1 ]]; then
  echo ""
  echo "Upload done. Install manually with admin (see README / doc §4.6.3)."
  exit 0
fi

echo ""
echo "== Step 3: admin login (Cookie, form) =="
_admin_login
echo "Admin cookie: ${ADMIN_COOKIE}"

echo ""
echo "== Step 4: admin install skill =="
echo "WARN: Install 按 admin 的 user_id 解析 Thread 路径；文件在 Owner=${OWNER} 目录下时可能 404。"
echo "      若 404，请用 §下方「admin 同用户完整链路」或运维 unzip。"
INSTALL_BODY="$(curl -sS -w "\nHTTP_STATUS=%{http_code}" -X POST "${GATEWAY}/api/skills/install" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: ${CSRF}" \
  -b "${ADMIN_COOKIE}" \
  -d "{\"thread_id\":\"${THREAD_ID}\",\"path\":\"${VPATH}\"}")"
echo "$INSTALL_BODY"

echo ""
echo "== Step 5: list custom skills (zhangsan vs admin session) =="
echo "--- zhangsan (Internal Token) ---"
curl -sS "${GATEWAY}/api/skills/custom" \
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}" \
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}"
echo ""
echo "--- admin (Cookie) ---"
curl -sS "${GATEWAY}/api/skills/custom" \
  -H "X-CSRF-Token: ${CSRF}" \
  -b "${ADMIN_COOKIE}"
echo ""
