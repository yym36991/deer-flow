#!/usr/bin/env bash
# 58 云效 / 宿主机直启 Gateway（无 Docker Compose）
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/cloud_env.sh"

ROOT="${DEER_FLOW_PROJECT_ROOT}"

mkdir -p "$DEER_FLOW_HOME" "$DEER_FLOW_LOG_DIR"

WORKERS="${GATEWAY_WORKERS:-1}"
UVICORN="${ROOT}/backend/.venv/bin/uvicorn"
if [ ! -x "$UVICORN" ]; then
  echo "ERROR: missing $UVICORN — run uv sync in ${ROOT}/backend first" >&2
  exit 1
fi

cd "${ROOT}/backend"
exec "$UVICORN" app.gateway.app:app --host 0.0.0.0 --port "${PORT:-8001}" --workers "$WORKERS"
