#!/usr/bin/env bash
# LangSmith 本地 Docker 部署（官方 compose，需 Enterprise License Key）
#
# 目录：/Users/a58/cdb/langsmith（与 deer-flow 同级，勿放进仓库）
#
# 用法：
#   bash scripts/verify-api/setup-langsmith-local.sh install
#   LANGSMITH_LICENSE_KEY=你的key bash scripts/verify-api/setup-langsmith-local.sh up
#   bash scripts/verify-api/setup-langsmith-local.sh down
#   bash scripts/verify-api/setup-langsmith-local.sh deerflow-env
#
# UI: http://localhost:1980
# DeerFlow 对接：
#   LANGSMITH_TRACING=true
#   LANGSMITH_ENDPOINT=http://localhost:1984/api/v1   # 或按 UI 提示的 API 地址
#   LANGSMITH_API_KEY=<在 LangSmith UI 创建的 key>
#   LANGSMITH_PROJECT=deer-flow
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LANGSMITH_DIR="$(cd "$ROOT/.." && pwd)/langsmith"
HELM_COMPOSE_BASE="https://raw.githubusercontent.com/langchain-ai/helm/main/charts/langsmith/docker-compose"

cmd="${1:-}"

fetch_file() {
  local name="$1"
  curl -fsSL "${HELM_COMPOSE_BASE}/${name}" -o "$LANGSMITH_DIR/$name"
}

do_install() {
  mkdir -p "$LANGSMITH_DIR"
  echo "==> 下载官方 LangSmith docker-compose 到 $LANGSMITH_DIR"
  fetch_file docker-compose.yaml
  fetch_file users.xml
  if [[ ! -f "$LANGSMITH_DIR/.env" ]]; then
    fetch_file .env.example
    cp "$LANGSMITH_DIR/.env.example" "$LANGSMITH_DIR/.env"
    # 本地学习：开启 basic auth，便于创建 API Key
    cat >>"$LANGSMITH_DIR/.env" <<'EOF'

# --- local dev overrides (setup-langsmith-local.sh) ---
BASIC_AUTH_ENABLED=true
BASIC_AUTH_JWT_SECRET=deerflow-langsmith-local-jwt-secret
INITIAL_ORG_ADMIN_EMAIL=admin@deerflow.local
INITIAL_ORG_ADMIN_PASSWORD=Deerflow@Langsmith1
API_KEY_SALT=deerflow-langsmith-api-salt
LANGSMITH_URL=http://localhost:1980
EOF
    echo "==> 已生成 $LANGSMITH_DIR/.env（请设置 LANGSMITH_LICENSE_KEY）"
  else
    echo "==> 已存在 $LANGSMITH_DIR/.env"
  fi
  echo "==> 安装完成"
}

do_up() {
  do_install
  if [[ -z "${LANGSMITH_LICENSE_KEY:-}" ]]; then
    if grep -q '^LANGSMITH_LICENSE_KEY=your-license-key' "$LANGSMITH_DIR/.env" 2>/dev/null || \
       grep -q '^LANGSMITH_LICENSE_KEY=$' "$LANGSMITH_DIR/.env" 2>/dev/null; then
      echo "错误: 需要 LangSmith Enterprise License Key。" >&2
      echo "  向 LangChain 申请试用: https://www.langchain.com/contact-sales" >&2
      echo "  然后执行:" >&2
      echo "    LANGSMITH_LICENSE_KEY=你的key bash scripts/verify-api/setup-langsmith-local.sh up" >&2
      echo "  或在 $LANGSMITH_DIR/.env 中设置 LANGSMITH_LICENSE_KEY" >&2
      exit 1
    fi
  fi
  cd "$LANGSMITH_DIR"
  export $(grep -v '^#' .env | grep -v '^$' | xargs) 2>/dev/null || true
  if [[ -n "${LANGSMITH_LICENSE_KEY:-}" ]]; then
    export LANGSMITH_LICENSE_KEY
  fi
  echo "==> 拉取镜像（首次较慢）..."
  docker compose pull
  echo "==> 启动 LangSmith..."
  docker compose up -d
  echo
  echo "LangSmith UI: http://localhost:1980"
  echo "管理员: admin@deerflow.local / Deerflow@Langsmith1"
  echo "Backend API: http://localhost:1984"
  echo "下一步: 在 UI 创建 Project + API Key，然后运行:"
  echo "  bash scripts/verify-api/setup-langsmith-local.sh deerflow-env"
}

do_down() {
  cd "$LANGSMITH_DIR"
  docker compose down
}

do_deerflow_env() {
  cat <<'EOF'
# 追加到 deer-flow/.env 后重启 Gateway（API Key 需在 http://localhost:1980 创建）:
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=http://localhost:1984/api/v1
LANGSMITH_API_KEY=在LangSmith_UI创建的key
LANGSMITH_PROJECT=deer-flow
EOF
}

case "$cmd" in
  install) do_install ;;
  up) do_up ;;
  down) do_down ;;
  deerflow-env) do_deerflow_env ;;
  *)
    echo "用法: $0 {install|up|down|deerflow-env}" >&2
    exit 1
    ;;
esac
