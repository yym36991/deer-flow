#!/usr/bin/env bash
# 58 云效「关闭脚本」— 停止 DeerFlow Gateway（uvicorn on PORT，默认 8001）
#
# 用法（《版本管理》关闭脚本）：
#   bash /opt/deer-flow/scripts/cloud_stop_gateway.sh
#
# 环境变量：
#   PORT  默认 8001
set -euo pipefail

PORT="${PORT:-8001}"
PATTERN="uvicorn app.gateway.app:app.*--port ${PORT}"

pids="$(pgrep -f "${PATTERN}" 2>/dev/null || true)"
if [ -z "${pids}" ]; then
  echo "No DeerFlow Gateway uvicorn process on port ${PORT}"
  exit 0
fi

echo "Stopping DeerFlow Gateway (port ${PORT}): ${pids}"
kill -TERM ${pids} 2>/dev/null || true

deadline=$(( $(date +%s) + 30 ))
while [ "$(date +%s)" -lt "${deadline}" ]; do
  remaining="$(pgrep -f "${PATTERN}" 2>/dev/null || true)"
  [ -z "${remaining}" ] && break
  sleep 1
done

remaining="$(pgrep -f "${PATTERN}" 2>/dev/null || true)"
if [ -n "${remaining}" ]; then
  echo "Force kill: ${remaining}" >&2
  kill -KILL ${remaining} 2>/dev/null || true
fi

echo "DeerFlow Gateway stopped"
