#!/usr/bin/env bash
# 58 云效「探测脚本」— Gateway 直启（端口 8001，无 Docker Compose）
set -euo pipefail

ROOT="${DEER_FLOW_DEPLOY_ROOT:-/opt/deer-flow}"
PORT="${PORT:-8001}"
BASE_URL="${DEER_FLOW_HEALTH_URL:-http://127.0.0.1:${PORT}}"

curl -fsS --max-time 5 "${BASE_URL%/}/health" >/dev/null

echo "OK"
