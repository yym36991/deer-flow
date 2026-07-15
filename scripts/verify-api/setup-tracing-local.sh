#!/usr/bin/env bash
# 本地可观测性（Trace）部署辅助脚本
#
# 说明：
# - LangSmith 完整自托管需要 Enterprise License，个人学习推荐用 LangSmith Cloud（见下方方案 A）
# - 本脚本部署的是 Langfuse（开源、MIT），DeerFlow 已内置支持，UI/概念与 LangSmith 类似
# - 基础设施目录放在 deer-flow 同级：/Users/a58/cdb/langfuse（不要放进 deer-flow 仓库内）
#
# 用法：
#   bash scripts/verify-api/setup-tracing-local.sh install   # 拉取 compose 到 ../langfuse
#   bash scripts/verify-api/setup-tracing-local.sh up       # 启动 Langfuse（UI: http://localhost:3100）
#   bash scripts/verify-api/setup-tracing-local.sh down     # 停止
#   bash scripts/verify-api/setup-tracing-local.sh keys     # 打印需在 deer-flow/.env 里配置的 Key
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LANGFUSE_DIR="$(cd "$ROOT/.." && pwd)/langfuse"

cmd="${1:-}"

write_env_if_missing() {
  if [[ -f "$LANGFUSE_DIR/.env" ]]; then
    echo "==> 已存在 $LANGFUSE_DIR/.env，跳过生成"
    return
  fi
  local salt enc nextauth pgpass redis chpass minio pk sk
  salt="$(openssl rand -base64 16 | tr -d '\n')"
  enc="$(openssl rand -hex 32)"
  nextauth="$(openssl rand -base64 32 | tr -d '\n')"
  pgpass="langfuse_dev_$(openssl rand -hex 8)"
  redis="redis_dev_$(openssl rand -hex 8)"
  chpass="ch_dev_$(openssl rand -hex 8)"
  minio="minio_dev_$(openssl rand -hex 8)"
  pk="pk-lf-deerflow-local-$(openssl rand -hex 6)"
  sk="sk-lf-deerflow-local-$(openssl rand -hex 12)"
  cat >"$LANGFUSE_DIR/.env" <<EOF
NEXTAUTH_URL=http://localhost:3100
NEXTAUTH_SECRET=${nextauth}
SALT=${salt}
ENCRYPTION_KEY=${enc}
DATABASE_URL=postgresql://postgres:${pgpass}@postgres:5432/postgres
POSTGRES_PASSWORD=${pgpass}
CLICKHOUSE_PASSWORD=${chpass}
REDIS_AUTH=${redis}
MINIO_ROOT_PASSWORD=${minio}
LANGFUSE_S3_EVENT_UPLOAD_SECRET_ACCESS_KEY=${minio}
LANGFUSE_S3_MEDIA_UPLOAD_SECRET_ACCESS_KEY=${minio}
LANGFUSE_S3_BATCH_EXPORT_SECRET_ACCESS_KEY=${minio}
LANGFUSE_INIT_USER_EMAIL=admin@deerflow.local
LANGFUSE_INIT_USER_NAME=deerflow-admin
LANGFUSE_INIT_USER_PASSWORD=deerflow-langfuse-dev
LANGFUSE_INIT_ORG_NAME=deerflow-local
LANGFUSE_INIT_PROJECT_NAME=deer-flow
LANGFUSE_INIT_PROJECT_PUBLIC_KEY=${pk}
LANGFUSE_INIT_PROJECT_SECRET_KEY=${sk}
EOF
  echo "==> 已生成 $LANGFUSE_DIR/.env"
}

write_override_if_missing() {
  if [[ -f "$LANGFUSE_DIR/docker-compose.override.yml" ]]; then
    return
  fi
  cat >"$LANGFUSE_DIR/docker-compose.override.yml" <<'EOF'
# 避免与 deer-flow Gateway(8001)、本机 Postgres(5432)、Redis(6379) 冲突
services:
  langfuse-web:
    ports:
      - "3100:3000"
  postgres:
    ports:
      - "127.0.0.1:55432:5432"
  redis:
    ports:
      - "127.0.0.1:56379:6379"
  clickhouse:
    ports:
      - "127.0.0.1:58123:8123"
      - "127.0.0.1:59000:9000"
  minio:
    ports:
      - "9190:9000"
      - "127.0.0.1:9191:9001"
EOF
}

do_install() {
  mkdir -p "$LANGFUSE_DIR"
  if [[ ! -f "$LANGFUSE_DIR/docker-compose.yml" ]]; then
    echo "==> 拉取 Langfuse docker-compose 到 $LANGFUSE_DIR"
    git clone --depth=1 https://github.com/langfuse/langfuse.git /tmp/langfuse-clone-$$
    cp /tmp/langfuse-clone-$$/docker-compose.yml "$LANGFUSE_DIR/"
    rm -rf /tmp/langfuse-clone-$$
  fi
  write_override_if_missing
  write_env_if_missing
  echo "==> 安装完成。目录: $LANGFUSE_DIR"
}

do_up() {
  do_install
  cd "$LANGFUSE_DIR"
  docker compose pull
  docker compose up -d
  echo
  echo "Langfuse UI: http://localhost:3100"
  echo "默认账号（首次 init）: admin@deerflow.local / deerflow-langfuse-dev"
  echo "下一步: bash scripts/verify-api/setup-tracing-local.sh keys"
}

do_down() {
  cd "$LANGFUSE_DIR"
  docker compose down
}

do_keys() {
  if [[ ! -f "$LANGFUSE_DIR/.env" ]]; then
    echo "请先运行: bash scripts/verify-api/setup-tracing-local.sh install" >&2
    exit 1
  fi
  # shellcheck disable=SC1090
  source "$LANGFUSE_DIR/.env"
  echo "在 deer-flow/.env 追加或取消注释以下内容，然后重启 Gateway："
  echo
  cat <<EOF
LANGFUSE_TRACING=true
LANGFUSE_PUBLIC_KEY=${LANGFUSE_INIT_PROJECT_PUBLIC_KEY}
LANGFUSE_SECRET_KEY=${LANGFUSE_INIT_PROJECT_SECRET_KEY}
LANGFUSE_BASE_URL=http://localhost:3100
EOF
}

case "$cmd" in
  install) do_install ;;
  up) do_up ;;
  down) do_down ;;
  keys) do_keys ;;
  *)
    echo "用法: $0 {install|up|down|keys}" >&2
    exit 1
    ;;
esac
