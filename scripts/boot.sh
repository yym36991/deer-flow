#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/cloud_env.sh"

mkdir -p "$DEER_FLOW_HOME" "$DEER_FLOW_LOG_DIR"

# 有脚本则用（新包）；没有则直接启动
if [ -x "${DEER_FLOW_PROJECT_ROOT}/scripts/cloud_bootstrap_gateway.sh" ]; then
  exec bash "${DEER_FLOW_PROJECT_ROOT}/scripts/cloud_bootstrap_gateway.sh"
fi

cd "${DEER_FLOW_PROJECT_ROOT}/backend"
exec "${DEER_FLOW_PROJECT_ROOT}/backend/.venv/bin/uvicorn" app.gateway.app:app \
  --host 0.0.0.0 --port "${PORT:-8001}" --workers "${GATEWAY_WORKERS:-1}"
