#!/usr/bin/env bash
# 人在回路（Human-in-the-loop）API 测试：ask_clarification → 用户回复 → 继续执行
#
# 用法：
#   bash scripts/verify-api/test-human-in-the-loop.sh
#   bash scripts/verify-api/test-human-in-the-loop.sh step2 <tool_call_id>
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

INTERNAL_TOKEN="${DEER_FLOW_INTERNAL_AUTH_TOKEN:-X-DeerFlow-Internal-Token-valid}"
OWNER="${DEER_FLOW_OWNER_USER_ID:-zhangsan}"
GATEWAY="${DEER_FLOW_GATEWAY_URL:-http://127.0.0.1:8001}"
THREAD_ID="${THREAD_ID:-hitl-api-test-007}"
STEP1_OUT="${TMPDIR:-/tmp}/deerflow-hitl-step1.sse"
STEP2_JSON="${TMPDIR:-/tmp}/deerflow-hitl-step2.json"

auth_headers=(
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}"
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}"
)

extract_tool_call_id() {
  python3 - "$1" <<'PY'
import json, sys

text = open(sys.argv[1], encoding="utf-8").read()
last_id = None
for line in text.splitlines():
    if not line.startswith("data: "):
        continue
    payload = line[6:]
    if payload in ("null", ""):
        continue
    try:
        obj = json.loads(payload)
    except json.JSONDecodeError:
        continue
    for msg in reversed(obj.get("messages") or []):
        if msg.get("type") == "tool" and msg.get("name") == "ask_clarification":
            hi = (msg.get("artifact") or {}).get("human_input") or {}
            if hi.get("tool_call_id"):
                last_id = hi["tool_call_id"]
                break
            if msg.get("tool_call_id"):
                last_id = msg["tool_call_id"]
                break
        if msg.get("type") == "ai":
            for tc in msg.get("tool_calls") or []:
                if tc.get("name") == "ask_clarification" and tc.get("id"):
                    last_id = tc["id"]
                    break
print(last_id or "")
PY
}

step2_body() {
  local tool_call_id="$1"
  local request_id="clarification:${tool_call_id}"
  cat >"$STEP2_JSON" <<EOF
{
  "assistant_id": "lead_agent",
  "input": {
    "messages": [
      {
        "role": "human",
        "content": "测试环境",
        "additional_kwargs": {
          "hide_from_ui": true,
          "human_input_response": {
            "version": 1,
            "kind": "human_input_response",
            "source": "ask_clarification",
            "request_id": "${request_id}",
            "response_kind": "option",
            "option_id": "option-2",
            "value": "测试环境"
          }
        }
      }
    ]
  },
  "context": {
    "subagent_enabled": false,
    "is_plan_mode": false,
    "thinking_enabled": false,
    "model_name": "chatling-plus"
  },
  "config": {
    "configurable": {
      "thread_id": "${THREAD_ID}"
    }
  },
  "metadata": {
    "source": "hitl-api-test-reply"
  },
  "on_disconnect": "continue"
}
EOF
  echo "$STEP2_JSON"
}

if [[ "${1:-}" == "step2" && -n "${2:-}" ]]; then
  step2_body "$2" >/dev/null
  echo "==> Step 2: 提交用户在回路回复 (tool_call_id=$2)"
  curl -N -X POST "${GATEWAY}/api/runs/stream" \
    -H "Content-Type: application/json" \
    -H "Accept: text/event-stream" \
    "${auth_headers[@]}" \
    -d @"$STEP2_JSON"
  exit 0
fi

echo "==> Step 1: 触发 ask_clarification（同一 thread: ${THREAD_ID}）"
echo "    输出保存到: ${STEP1_OUT}"
curl -N -s -X POST "${GATEWAY}/api/runs/stream" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  "${auth_headers[@]}" \
  -d @scripts/verify-api/hitl-step1-ask.json | tee "$STEP1_OUT"

echo
TOOL_CALL_ID="$(extract_tool_call_id "$STEP1_OUT")"
if [[ -z "$TOOL_CALL_ID" ]]; then
  echo "未在 Step 1 输出中找到 ask_clarification。请检查 SSE 里是否有 tool_calls.name=ask_clarification" >&2
  echo "可手动: bash $0 step2 <tool_call_id>" >&2
  exit 1
fi

echo
echo "==> 检测到 clarification tool_call_id: ${TOOL_CALL_ID}"
step2_body "$TOOL_CALL_ID" >/dev/null

echo "==> Step 2: 用户回答「测试环境」，继续 run"
curl -N -X POST "${GATEWAY}/api/runs/stream" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  "${auth_headers[@]}" \
  -d @"$STEP2_JSON"

echo
