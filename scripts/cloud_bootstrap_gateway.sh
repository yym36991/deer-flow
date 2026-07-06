#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/cloud_env.sh"

ROOT="${DEER_FLOW_PROJECT_ROOT}"
export UV_INDEX_URL="${UV_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"

# 平台把 tar 放在 /opt/ 时，常见文件名模式（可按实际改 DEER_FLOW_CODE_ARCHIVE）
find_code_archive() {
  local pattern="${DEER_FLOW_CODE_ARCHIVE:-/opt/deer-flow.*.tar.gz}"
  # shellcheck disable=SC2086
  ls -t $pattern 2>/dev/null | head -n 1 || true
}

ensure_code_tree() {
  if [ -f "${ROOT}/backend/pyproject.toml" ]; then
    return 0
  fi

  local archive
  archive="$(find_code_archive)"
  if [ -z "${archive}" ] || [ ! -f "${archive}" ]; then
    echo "ERROR: ${ROOT}/backend/pyproject.toml missing and no tar at /opt/deer-flow.*.tar.gz" >&2
    echo "Upload cloud_pack tarball in Version Management (save dir /opt/) or set DEER_FLOW_CODE_ARCHIVE." >&2
    exit 1
  fi

  echo "Extracting code package: ${archive}"
  mkdir -p /opt
  tar -xzf "${archive}" -C /opt/
  if [ ! -f "${ROOT}/backend/pyproject.toml" ]; then
    echo "ERROR: after extract, expected ${ROOT}/backend/pyproject.toml" >&2
    exit 1
  fi
}

ensure_venv() {
  local lock="${ROOT}/backend/uv.lock"
  local stamp="${DEER_FLOW_HOME:-${ROOT}/data/.deer-flow}/.uv-sync.stamp"
  local venv_py="${ROOT}/backend/.venv/bin/python"

  mkdir -p "$(dirname "${stamp}")"

  if [ -f "${venv_py}" ] && [ -f "${stamp}" ] && [ -f "${lock}" ] && cmp -s "${lock}" "${stamp}"; then
    echo "uv sync skipped (uv.lock unchanged)"
    return 0
  fi

  # Optional image with pre-baked .venv (Dockerfile.58-gateway.venv)
  if [ "${DEER_FLOW_VENV_BAKED:-}" = "1" ] && [ -x "${venv_py}" ]; then
    if "${venv_py}" -c "import asyncpg" 2>/dev/null; then
      echo "uv sync skipped (DEER_FLOW_VENV_BAKED=1 and asyncpg present)"
      if [ -f "${lock}" ]; then
        cp -f "${lock}" "${stamp}"
      fi
      return 0
    fi
  fi

  UV_SYNC_ARGS=(sync --all-packages)
  if grep -qE 'backend:[[:space:]]*postgres' "${ROOT}/config.deploy.yaml" 2>/dev/null \
    || grep -qE 'backend:[[:space:]]*postgres' "${ROOT}/config.yaml" 2>/dev/null; then
    UV_SYNC_ARGS+=(--extra postgres)
    echo "Postgres backend detected — uv sync --extra postgres"
  fi

  echo "Running uv ${UV_SYNC_ARGS[*]} in ${ROOT}/backend ..."
  (cd "${ROOT}/backend" && uv "${UV_SYNC_ARGS[@]}")
  if [ -f "${lock}" ]; then
    cp -f "${lock}" "${stamp}"
  else
    : > "${stamp}"
  fi
}

ensure_code_tree
ensure_venv
exec bash "${ROOT}/scripts/cloud_start_gateway.sh"
