#!/usr/bin/env bash
# 本地启动 DeerFlow Gateway（仅 API，不依赖 IM channel / nginx）
# 用法：bash scripts/verify-api/start-gateway.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if [[ ! -f config.yaml ]]; then
  echo "错误: 未找到 config.yaml。请执行: cp config.example.yaml config.yaml 并按需修改。" >&2
  exit 1
fi

echo "==> 同步 backend 依赖（postgres extra）"
cd "$ROOT/backend"
uv sync --extra postgres

echo "==> 启动 Gateway http://0.0.0.0:8001"
echo "    配置文件: $ROOT/config.yaml"
echo "    健康检查: curl http://127.0.0.1:8001/health"
echo "    API 文档: http://127.0.0.1:8001/docs"
echo "    按 Ctrl+C 停止"
echo

# 覆盖 shell 中可能残留的错误 DEER_FLOW_* 环境变量
export DEER_FLOW_PROJECT_ROOT="$ROOT"
export DEER_FLOW_CONFIG_PATH="$ROOT/config.yaml"

# Internal API（共享密钥 + X-DeerFlow-Owner-User-Id 做用户隔离）
# 生产请改为长随机串，且仅内网可达；勿提交到 git。
export DEER_FLOW_INTERNAL_AUTH_TOKEN="${DEER_FLOW_INTERNAL_AUTH_TOKEN:-X-DeerFlow-Internal-Token-valid}"

PYTHONPATH=. PYTHONIOENCODING=utf-8 PYTHONUTF8=1 \
  uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001 --reload
