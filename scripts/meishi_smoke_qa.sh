#!/usr/bin/env bash
# 在部署机上自测美事「问答中」回调（需与 config.deploy.yaml 中 meishi.secret 一致）
#  bash scripts/meishi_smoke_qa.sh '密码'
set -euo pipefail

BASE_URL="${MEISHI_SMOKE_BASE_URL:-http://127.0.0.1:8001}"
SECRET="${1:-}"
if [ -z "$SECRET" ]; then
  CFG="${DEER_FLOW_CONFIG_PATH:-/opt/deer-flow/config.deploy.yaml}"
  SECRET="$(grep -E '^[[:space:]]*secret:' "$CFG" | head -1 | sed -E 's/.*secret:[[:space:]]*"?([^"]+)"?.*/\1/')"
fi
if [ -z "$SECRET" ]; then
  echo "用法: $0 <meishi.secret>  或设置 DEER_FLOW_CONFIG_PATH" >&2
  exit 1
fi

TS="$(date +%s%3N 2>/dev/null || python3 -c 'import time; print(int(time.time()*1000))')"
RANDOM_HEX="$(openssl rand -hex 3 2>/dev/null || echo 543009)"
SIGN="$(python3 -c "import hashlib; print(hashlib.md5(f'${TS}${SECRET}${RANDOM_HEX}'.encode()).hexdigest())")"

MODE="${MEISHI_SMOKE_MODE:-sse}"
if [ "$MODE" = "blocking" ]; then
  echo "POST ${BASE_URL}/api/meishi/callback/qa (JSON blocking，与美事非流式一致)"
  ACCEPT="application/json"
  CURL_EXTRA=()
else
  echo "POST ${BASE_URL}/api/meishi/callback/qa (SSE)"
  ACCEPT="text/event-stream"
  CURL_EXTRA=(-N)
fi

curl -sS "${CURL_EXTRA[@]}" -X POST "${BASE_URL}/api/meishi/callback/qa" \
  -H "Content-Type: application/json; charset=utf-8" \
  -H "Accept: ${ACCEPT}" \
  -D /tmp/meishi_smoke_headers.txt \
  -d "{\"userOa\":\"smoke_test\",\"msg\":\"今天几月几号？\",\"timestamp\":\"${TS}\",\"random\":\"${RANDOM_HEX}\",\"signStr\":\"${SIGN}\",\"senderId\":\"s1\",\"toId\":\"t1\"}"
echo
echo "--- Response headers ---"
grep -i content-type /tmp/meishi_smoke_headers.txt || true
