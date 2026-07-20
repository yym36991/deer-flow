#!/usr/bin/env bash
# 多轮 HITL：Step1 ask → Step2 答环境 → Step3 答 OS → … 直到无 pending
#
# 用法：bash scripts/verify-api/test-human-in-the-loop-multi.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

INTERNAL_TOKEN="${DEER_FLOW_INTERNAL_AUTH_TOKEN:-X-DeerFlow-Internal-Token-valid}"
OWNER="${DEER_FLOW_OWNER_USER_ID:-zhangsan}"
GATEWAY="${DEER_FLOW_GATEWAY_URL:-http://127.0.0.1:8001}"
THREAD_ID="${THREAD_ID:-hitl-api-test-008}"

auth_headers=(
  -H "X-DeerFlow-Internal-Token: ${INTERNAL_TOKEN}"
  -H "X-DeerFlow-Owner-User-Id: ${OWNER}"
)

python3 <<PY
import json, os, subprocess, sys

GATEWAY = os.environ.get("DEER_FLOW_GATEWAY_URL", "http://127.0.0.1:8001")
TOKEN = os.environ.get("DEER_FLOW_INTERNAL_AUTH_TOKEN", "X-DeerFlow-Internal-Token-valid")
OWNER = os.environ.get("DEER_FLOW_OWNER_USER_ID", "zhangsan")
STEP1 = "scripts/verify-api/hitl-step1-ask.json"
THREAD = os.environ.get("THREAD_ID") or json.load(open(STEP1, encoding="utf-8"))["config"]["configurable"]["thread_id"]

def step1_body_path():
    body = json.load(open(STEP1, encoding="utf-8"))
    body["config"]["configurable"]["thread_id"] = THREAD
    path = "/tmp/hitl-multi-step1.json"
    json.dump(body, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return path

ANSWERS = [
    ("测试环境", "option-2"),
    ("Windows", "option-2"),
    ("手动部署", "option-1"),
]

def curl_stream(body_path, out_path):
    cmd = [
        "curl", "-N", "-s", "-X", "POST", f"{GATEWAY}/api/runs/stream",
        "-H", "Content-Type: application/json",
        "-H", "Accept: text/event-stream",
        "-H", f"X-DeerFlow-Internal-Token: {TOKEN}",
        "-H", f"X-DeerFlow-Owner-User-Id: {OWNER}",
        "-d", f"@{body_path}",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    open(out_path, "w", encoding="utf-8").write(r.stdout)
    return r.stdout

def last_values_obj(sse_text):
    obj = None
    for line in sse_text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload in ("null", ""):
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
    return obj

def pending_request(obj):
    if not obj:
        return None
    answered = set()
    for msg in obj.get("messages") or []:
        if msg.get("type") == "human":
            hr = (msg.get("additional_kwargs") or {}).get("human_input_response") or {}
            if hr.get("request_id"):
                answered.add(hr["request_id"])
    pending = None
    for msg in obj.get("messages") or []:
        if msg.get("type") == "tool" and msg.get("name") == "ask_clarification":
            hi = (msg.get("artifact") or {}).get("human_input") or {}
            rid = hi.get("request_id")
            if rid and rid not in answered:
                pending = hi
    return pending

def make_reply(pending, value, option_id=None):
    resp = {
        "version": 1,
        "kind": "human_input_response",
        "source": "ask_clarification",
        "request_id": pending["request_id"],
        "response_kind": "option" if option_id else "text",
        "value": value,
    }
    if option_id:
        resp["option_id"] = option_id
    return {
        "assistant_id": "lead_agent",
        "input": {"messages": [{
            "role": "human",
            "content": value,
            "additional_kwargs": {"hide_from_ui": True, "human_input_response": resp},
        }]},
        "context": {
            "subagent_enabled": False,
            "is_plan_mode": False,
            "thinking_enabled": False,
            "model_name": "chatling-plus",
        },
        "config": {"configurable": {"thread_id": THREAD}},
        "metadata": {"source": "hitl-api-test-reply"},
        "on_disconnect": "continue",
    }

print(f"==> Thread: {THREAD}")
print("==> Step 1: 触发 ask_clarification")
sse = curl_stream(step1_body_path(), "/tmp/hitl-multi-step1.sse")
obj = last_values_obj(sse)
p = pending_request(obj)
if not p:
    sys.exit("Step1: 未检测到 pending ask_clarification")
sandbox = (obj or {}).get("sandbox")
td = (obj or {}).get("thread_data")
print(f"    Q1: {p.get('question')}")
print(f"    request_id: {p.get('request_id')}")
if sandbox:
    print(f"    sandbox: {sandbox}")
if td:
    print(f"    workspace: {td.get('workspace_path', '')}")

prev_sse = sse
for i, (value, opt_id) in enumerate(ANSWERS, start=2):
    obj = last_values_obj(prev_sse)
    p = pending_request(obj)
    if not p:
        ai_msgs = [m for m in (obj or {}).get("messages", []) if m.get("type") == "ai" and m.get("content")]
        if ai_msgs:
            print(f"\n==> 无新 pending，AI: {ai_msgs[-1]['content'][:160]}...")
        break
    body = make_reply(p, value, opt_id)
    path = f"/tmp/hitl-multi-step{i}.json"
    json.dump(body, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n==> Step {i}: 回复「{value}» ({p.get('request_id')})")
    prev_sse = curl_stream(path, f"/tmp/hitl-multi-step{i}.sse")
    obj = last_values_obj(prev_sse)
    np = pending_request(obj)
    if np:
        print(f"    下一轮 Q: {np.get('question')}")
        print(f"    request_id: {np.get('request_id')}")
        opts = [o.get("label") for o in (np.get("options") or [])]
        if opts:
            print(f"    options: {opts}")
    else:
        ai_msgs = [m for m in (obj or {}).get("messages", []) if m.get("type") == "ai" and m.get("content")]
        print("    无新 pending" + (f"；AI: {ai_msgs[-1]['content'][:120]}..." if ai_msgs else ""))

print("\n==> 多轮 HITL 走查完成")
PY
