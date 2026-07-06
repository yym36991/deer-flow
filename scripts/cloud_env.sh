#!/usr/bin/env bash
# 云平台 Gateway 公共环境（被其他 cloud_*.sh source，勿直接 exec）
ROOT="${DEER_FLOW_DEPLOY_ROOT:-/opt/deer-flow}"

export DEER_FLOW_PROJECT_ROOT="${DEER_FLOW_PROJECT_ROOT:-$ROOT}"
export DEER_FLOW_HOME="${DEER_FLOW_HOME:-$ROOT/data/.deer-flow}"
export DEER_FLOW_CONFIG_PATH="${DEER_FLOW_CONFIG_PATH:-$ROOT/config.deploy.yaml}"
export DEER_FLOW_EXTENSIONS_CONFIG_PATH="${DEER_FLOW_EXTENSIONS_CONFIG_PATH:-$ROOT/extensions_config.json}"
export DEER_FLOW_LOG_DIR="${DEER_FLOW_LOG_DIR:-$ROOT/logs}"
export PYTHONPATH="${DEER_FLOW_PROJECT_ROOT}/backend"
export LANG="${LANG:-C.UTF-8}"
export LC_ALL="${LC_ALL:-C.UTF-8}"
export DEER_FLOW_INTERNAL_AUTH_TOKEN="${DEER_FLOW_INTERNAL_AUTH_TOKEN:-deerflow-58-internal}"
export UV_INDEX_URL="${UV_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"

# 云平台密钥：优先平台注入的环境变量；否则读项目根 .env
if [ -f "${DEER_FLOW_PROJECT_ROOT}/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "${DEER_FLOW_PROJECT_ROOT}/.env"
  set +a
fi
