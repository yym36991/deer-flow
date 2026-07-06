#!/usr/bin/env bash
# 部署机一键排查：进程、端口、健康检查、日志、venv、配置路径
set -uo pipefail

ROOT="${DEER_FLOW_DEPLOY_ROOT:-/opt/deer-flow}"
PORT="${PORT:-8001}"
LOG="${DEER_FLOW_LOG_DIR:-${ROOT}/logs}/gateway_0.log"

section() { echo; echo "======== $1 ========"; }

section "Time / env"
date
echo "DEER_FLOW_CONFIG_PATH=${DEER_FLOW_CONFIG_PATH:-${ROOT}/config.deploy.yaml}"
echo "DEER_FLOW_HOME=${DEER_FLOW_HOME:-${ROOT}/data/.deer-flow}"
echo "DEER_FLOW_INTERNAL_AUTH_TOKEN=${DEER_FLOW_INTERNAL_AUTH_TOKEN:-<unset>}"
echo "PORT=${PORT}"

section "Process (uvicorn)"
ps aux 2>/dev/null | grep -E '[u]vicorn|[d]eerflow' || echo "(no uvicorn process)"

section "Listen :${PORT}"
if command -v ss >/dev/null 2>&1; then
  ss -lntp 2>/dev/null | grep ":${PORT}" || echo "(nothing listening on ${PORT})"
elif command -v netstat >/dev/null 2>&1; then
  netstat -lntp 2>/dev/null | grep ":${PORT}" || echo "(nothing listening on ${PORT})"
else
  echo "ss/netstat not available"
fi

section "Files"
for f in \
  "${ROOT}/config.deploy.yaml" \
  "${ROOT}/backend/pyproject.toml" \
  "${ROOT}/backend/.venv/bin/uvicorn" \
  "${ROOT}/backend/.venv/bin/python"; do
  if [ -e "$f" ]; then
    ls -la "$f"
  else
    echo "MISSING: $f"
  fi
done

section "Required env"
for var in CHATGPT_58CORP_API_KEY DATABASE_URL; do
  if [ -n "${!var:-}" ]; then
    echo "${var}=set"
  else
    echo "${var}=MISSING (set in cloud platform or ${ROOT}/.env)"
  fi
done
if curl -fsS --max-time 3 "http://127.0.0.1:${PORT}/health" 2>/dev/null; then
  echo "GET /health OK"
else
  echo "GET /health FAILED (connection refused or timeout)"
fi

section "Recent logs"
if [ -f "${LOG}" ]; then
  tail -n 40 "${LOG}"
else
  echo "No ${LOG}"
fi

section "startup.log"
STARTUP="${DEER_FLOW_LOG_DIR:-${ROOT}/logs}/startup.log"
if [ -f "${STARTUP}" ]; then
  tail -n 40 "${STARTUP}"
else
  echo "No ${STARTUP}"
fi
