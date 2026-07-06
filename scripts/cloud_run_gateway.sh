#!/usr/bin/env bash
# 前台启动 Gateway，stdout/stderr 写入 startup.log（排查启动崩溃）
set -euo pipefail

ROOT="${DEER_FLOW_DEPLOY_ROOT:-/opt/deer-flow}"
LOG_DIR="${DEER_FLOW_LOG_DIR:-${ROOT}/logs}"
STARTUP_LOG="${DEER_FLOW_STARTUP_LOG:-${LOG_DIR}/startup.log}"

mkdir -p "$LOG_DIR"
{
  echo "======== $(date -Iseconds) cloud_run_gateway ========"
  echo "USER=$(id)"
  echo "PWD=$(pwd)"
  echo "DEER_FLOW_CONFIG_PATH=${DEER_FLOW_CONFIG_PATH:-}"
  echo "DEER_FLOW_HOME=${DEER_FLOW_HOME:-}"
  if [ -f "${DEER_FLOW_CONFIG_PATH:-${ROOT}/config.deploy.yaml}" ]; then
    grep -A3 '^database:' "${DEER_FLOW_CONFIG_PATH:-${ROOT}/config.deploy.yaml}" || true
  fi
} >>"$STARTUP_LOG"

if [ -x "${ROOT}/scripts/cloud_bootstrap_gateway.sh" ]; then
  exec >>"$STARTUP_LOG" 2>&1
  exec bash "${ROOT}/scripts/cloud_bootstrap_gateway.sh"
fi

exec >>"$STARTUP_LOG" 2>&1
exec bash "${ROOT}/scripts/cloud_start_gateway.sh"
