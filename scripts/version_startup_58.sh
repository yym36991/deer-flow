#!/usr/bin/env bash
# 58 《版本管理》启动脚本全文 — 可整段粘贴到平台「启动脚本」框
# 逻辑：必要时解压 /opt/deer-flow.*.tar.gz → uv sync → 启动 Gateway
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/cloud_env.sh"

ROOT="${DEER_FLOW_PROJECT_ROOT}"

if [ ! -f "${ROOT}/backend/pyproject.toml" ]; then
  ARCHIVE=""
  for p in /opt/deer-flow.*.tar.gz /opt/deer-flow.tar.gz; do
    [ -f "$p" ] || continue
    ARCHIVE="$p"
    break
  done
  if [ -z "${ARCHIVE}" ]; then
    echo "ERROR: no code under ${ROOT} and no tar in /opt" >&2
    exit 1
  fi
  echo "Extracting ${ARCHIVE} ..."
  mkdir -p /opt
  tar -xzf "${ARCHIVE}" -C /opt/
fi

export DEER_FLOW_PROJECT_ROOT="${DEER_FLOW_PROJECT_ROOT:-$ROOT}"

if [ -x "${ROOT}/scripts/cloud_run_gateway.sh" ]; then
  exec bash "${ROOT}/scripts/cloud_run_gateway.sh"
fi

if [ -x "${ROOT}/scripts/cloud_bootstrap_gateway.sh" ]; then
  exec bash "${ROOT}/scripts/cloud_bootstrap_gateway.sh"
fi

# tar 内尚无 bootstrap 脚本时的兜底（与 cloud_bootstrap_gateway.sh 等价）
LOCK="${ROOT}/backend/uv.lock"
STAMP="${DEER_FLOW_HOME}/.uv-sync.stamp"
mkdir -p "${DEER_FLOW_HOME}" "${DEER_FLOW_LOG_DIR}"
if [ ! -x "${ROOT}/backend/.venv/bin/uvicorn" ] || \
   { [ -f "${LOCK}" ] && { [ ! -f "${STAMP}" ] || ! cmp -s "${LOCK}" "${STAMP}"; }; }; then
  UV_SYNC_ARGS=(sync --all-packages)
  if grep -qE 'backend:[[:space:]]*postgres' "${DEER_FLOW_CONFIG_PATH}" 2>/dev/null; then
    UV_SYNC_ARGS+=(--extra postgres)
  fi
  echo "Running uv ${UV_SYNC_ARGS[*]} ..."
  (cd "${ROOT}/backend" && uv "${UV_SYNC_ARGS[@]}")
  [ -f "${LOCK}" ] && cp -f "${LOCK}" "${STAMP}" || : > "${STAMP}"
fi

if [ ! -x "${ROOT}/backend/.venv/bin/uvicorn" ]; then
  echo "ERROR: venv missing after uv sync" >&2
  exit 1
fi
cd "${ROOT}/backend"
exec "${ROOT}/backend/.venv/bin/uvicorn" app.gateway.app:app \
  --host 0.0.0.0 --port "${PORT:-8001}" --workers "${GATEWAY_WORKERS:-1}"
