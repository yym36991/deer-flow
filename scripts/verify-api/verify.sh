#!/usr/bin/env bash
# 用 backend 虚拟环境运行验证脚本（自带 sqlalchemy 等依赖，无需系统 python）
# 用法: bash scripts/verify-api/verify.sh api_verify.py register
#       bash scripts/verify-api/verify.sh clear-database.py --yes
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT_NAME="${1:?用法: verify.sh <脚本名> [参数...]}"
shift

export DEER_FLOW_PROJECT_ROOT="$ROOT"
export DEER_FLOW_CONFIG_PATH="$ROOT/config.yaml"

cd "$ROOT/backend"
exec uv run python "$ROOT/scripts/verify-api/$SCRIPT_NAME" "$@"
