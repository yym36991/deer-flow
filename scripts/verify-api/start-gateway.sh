#!/usr/bin/env bash
# 本地启动 DeerFlow Gateway（仅 API，不依赖 IM channel）
# 用法：bash scripts/verify-api/start-gateway.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if [[ ! -f config.yaml ]]; then
  echo "错误: 未找到 config.yaml。请执行: cp config.example.yaml config.yaml 并按 README 修改。" >&2
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

# 覆盖 shell 中可能残留的错误 DEER_FLOW_* 环境变量（常见误指向 scripts/verify/config.verify.yaml）
export DEER_FLOW_PROJECT_ROOT="$ROOT"
export DEER_FLOW_CONFIG_PATH="$ROOT/config.yaml"

PYTHONPATH=. PYTHONIOENCODING=utf-8 PYTHONUTF8=1 \
  uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001 --reload
