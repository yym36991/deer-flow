#!/usr/bin/env bash
# 58 云效「首次启动 / 发版后」探测脚本 — 等待 uv sync 完成且 8001 监听后再 curl
#
# 平台若在 uv sync 期间立刻 curl /health，会 Connection refused 并销毁容器。
# 「探测间隔 200」通常是稳态周期，不是首启 grace period；请用本脚本作 check，或设首启延迟 ≥300s。
#
# 用法（《版本管理》探测脚本）：
#   bash /opt/deer-flow/scripts/cloud_check_gateway_startup.sh
#
# 环境变量：
#   DEER_FLOW_PROBE_MAX_WAIT_SEC  最长等待秒数（默认 300）
#   DEER_FLOW_PROBE_POLL_SEC      轮询间隔（默认 5）
#   PORT                          Gateway 端口（默认 8001）
set -euo pipefail

ROOT="${DEER_FLOW_DEPLOY_ROOT:-/opt/deer-flow}"
PORT="${PORT:-8001}"
BASE_URL="${DEER_FLOW_HEALTH_URL:-http://127.0.0.1:${PORT}}"
MAX_WAIT="${DEER_FLOW_PROBE_MAX_WAIT_SEC:-300}"
POLL="${DEER_FLOW_PROBE_POLL_SEC:-5}"

deadline=$(( $(date +%s) + MAX_WAIT ))
attempt=0

while [ "$(date +%s)" -lt "${deadline}" ]; do
  attempt=$((attempt + 1))
  if curl -fsS --max-time 5 "${BASE_URL%/}/health" >/dev/null 2>&1; then
    echo "OK (attempt=${attempt}, waited=$(( MAX_WAIT - (deadline - $(date +%s)) ))s approx)"
    exit 0
  fi
  # uv sync 进行中时正常 refused；继续等
  sleep "${POLL}"
done

echo "TIMEOUT after ${MAX_WAIT}s: ${BASE_URL}/health still unreachable" >&2
echo "Hint: see ${ROOT}/logs/startup.log and ensure start script blocks on cloud_bootstrap_gateway.sh" >&2
exit 1
