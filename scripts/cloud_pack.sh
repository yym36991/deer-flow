#!/usr/bin/env bash
# 打 58 自建镜像用上传包：deer-flow.<版本>.tar.gz（在项目根目录执行）
# 解压到 /opt/ => /opt/deer-flow/，在《版本管理》上传；启动见 version_startup_58.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

VERSION="${1:-$(date +%Y%m%d-%H%M)}"
OUT_DIR="${REPO_ROOT}/dist"
STAGE="${OUT_DIR}/deer-flow"
ARCHIVE="${OUT_DIR}/deer-flow.${VERSION}.tar.gz"

rm -rf "${STAGE}"
mkdir -p "${STAGE}" "${STAGE}/logs"
touch "${STAGE}/logs/.gitkeep"

copy_tree() {
  local src="$1"
  local dst="$2"
  mkdir -p "${dst}"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete \
      --exclude '.git' \
      --exclude '.vscode' \
      --exclude '.idea' \
      --exclude 'node_modules' \
      --exclude '.next' \
      --exclude '__pycache__' \
      --exclude '.venv' \
      --exclude '.deer-flow' \
      --exclude 'dist' \
      "${src}/" "${dst}/"
  else
    cp -R "${src}/." "${dst}/"
  fi
}

copy_tree "${REPO_ROOT}/backend" "${STAGE}/backend"
# 云上 gateway-only 模式不打包 frontend（省体积与构建时间）
if [ "${DEER_FLOW_PACK_INCLUDE_FRONTEND:-0}" = "1" ]; then
  copy_tree "${REPO_ROOT}/frontend" "${STAGE}/frontend"
fi
copy_tree "${REPO_ROOT}/docker" "${STAGE}/docker"
copy_tree "${REPO_ROOT}/skills" "${STAGE}/skills"
copy_tree "${REPO_ROOT}/scripts" "${STAGE}/scripts"
copy_tree "${REPO_ROOT}/contracts" "${STAGE}/contracts"

if [ ! -f "${REPO_ROOT}/config.deploy.yaml" ]; then
  echo "ERROR: missing ${REPO_ROOT}/config.deploy.yaml" >&2
  exit 1
fi
cp -f "${REPO_ROOT}/config.deploy.yaml" "${STAGE}/"
if [ -f "${REPO_ROOT}/SOUL.md" ]; then
  cp -f "${REPO_ROOT}/SOUL.md" "${STAGE}/SOUL.md"
fi
if [ -f "${REPO_ROOT}/extensions_config.deploy.json" ]; then
  cp -f "${REPO_ROOT}/extensions_config.deploy.json" "${STAGE}/extensions_config.json"
elif [ -f "${REPO_ROOT}/extensions_config.json" ]; then
  cp -f "${REPO_ROOT}/extensions_config.json" "${STAGE}/extensions_config.json"
else
  echo '{"mcpServers":{},"skills":{}}' > "${STAGE}/extensions_config.json"
fi

# docker-compose.yaml 引用 env_file；云主机密钥写入 .env（见 .env.cloud.example）
if [ -f "${REPO_ROOT}/.env.cloud.example" ] && [ ! -s "${STAGE}/.env" ]; then
  cp -f "${REPO_ROOT}/.env.cloud.example" "${STAGE}/.env"
else
  touch "${STAGE}/.env"
fi
if [ "${DEER_FLOW_PACK_INCLUDE_FRONTEND:-0}" = "1" ]; then
  mkdir -p "${STAGE}/frontend"
  touch "${STAGE}/frontend/.env"
fi

chmod +x "${STAGE}/scripts/cloud_"*.sh 2>/dev/null || true
chmod +x "${STAGE}/scripts/cloud_stop_gateway.sh" 2>/dev/null || true
chmod +x "${STAGE}/scripts/boot.sh" 2>/dev/null || true

mkdir -p "${OUT_DIR}"
rm -f "${ARCHIVE}"
# 避免 macOS 打出 ._xxx 元数据；Linux 解压时更干净
export COPYFILE_DISABLE=1
if tar --help 2>&1 | grep -q disable-copyfile; then
  tar --disable-copyfile -czf "${ARCHIVE}" -C "${OUT_DIR}" deer-flow
else
  tar -czf "${ARCHIVE}" -C "${OUT_DIR}" deer-flow
fi

echo "Created: ${ARCHIVE}"
echo "Size:           $(du -h "${ARCHIVE}" | cut -f1)"
echo "Note:           gateway-only pack (no frontend). Full UI: DEER_FLOW_PACK_INCLUDE_FRONTEND=1"
echo "Cloud extract:  mkdir -p /opt && tar -xzf deer-flow.${VERSION}.tar.gz -C /opt/"
echo "                => /opt/deer-flow/"
echo "Version start:  scripts/version_startup_58.sh (paste into 版本管理)"
echo "Health probe:   bash /opt/deer-flow/scripts/cloud_check_gateway.sh"
