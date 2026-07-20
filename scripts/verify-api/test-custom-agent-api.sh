#!/usr/bin/env bash
# 通过 HTTP API 为指定用户创建 custom agent，并流式对话验证。
# 前置：
#   1) config.yaml → agents_api.enabled: true
#   2) bash scripts/verify-api/start-gateway.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

INTERNAL_TOKEN="${DEER_FLOW_INTERNAL_AUTH_TOKEN:-X-DeerFlow-Internal-Token-valid}"
OWNER="${DEER_FLOW_OWNER_USER_ID:-yangyanmeng}"
GATEWAY="${DEER_FLOW_GATEWAY_URL:-http://127.0.0.1:8001}"

AUTH=(
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}"
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}"
)

echo "==> 1) 检查 agents_api 是否开启"
features="$(curl -s "${AUTH[@]}" "${GATEWAY}/api/features")"
echo "${features}"
echo "${features}" | grep -q '"enabled":true' || {
  echo "错误: agents_api 未开启。请在 config.yaml 设置 agents_api.enabled: true 并确保 Gateway 已加载配置。" >&2
  exit 1
}

echo
echo "==> 2) 创建 custom agent（POST /api/agents）"
create_code="$(curl -s -o /tmp/deerflow-create-agent.json -w '%{http_code}' \
  -X POST "${GATEWAY}/api/agents" \
  -H "Content-Type: application/json" \
  "${AUTH[@]}" \
  -d @scripts/verify-api/create-custom-agent.json)"
echo "HTTP ${create_code}"
cat /tmp/deerflow-create-agent.json
echo

if [[ "${create_code}" != "201" && "${create_code}" != "409" ]]; then
  echo "创建失败（409 表示已存在，可继续对话测试）" >&2
  [[ "${create_code}" == "409" ]] || exit 1
fi

echo
echo "==> 3) 列出该用户的 agents"
curl -s "${AUTH[@]}" "${GATEWAY}/api/agents" | python3 -m json.tool

echo
echo "==> 4) 用 custom agent 流式对话（assistant_id=yang-tech-advisor）"
curl -N -X POST "${GATEWAY}/api/runs/stream" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  "${AUTH[@]}" \
  -d @scripts/verify-api/chat-custom-agent.json

echo
echo
echo "==> 5) 磁盘路径（创建成功后应存在）"
echo "${ROOT}/.deer-flow/users/${OWNER}/agents/yang-tech-advisor/config.yaml"
echo "${ROOT}/.deer-flow/users/${OWNER}/agents/yang-tech-advisor/SOUL.md"
