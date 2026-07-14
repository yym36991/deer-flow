#!/usr/bin/env bash
# 一键跑通 API 验证主流程（默认不创建 admin，直接 register）
#
# 用法:
#   bash scripts/verify-api/run-verify.sh              # 用户 A：清库 → 注册 → 建 thread → 对话 → 查库
#   bash scripts/verify-api/run-verify.sh --init-admin # 含 init-admin
#   bash scripts/verify-api/run-verify.sh --message "北京天气怎么样"
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VERIFY="$ROOT/scripts/verify-api/verify.sh"
INIT_ADMIN=false
MESSAGE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --init-admin) INIT_ADMIN=true; shift ;;
    -m|--message) MESSAGE="$2"; shift 2 ;;
    *) echo "未知参数: $1" >&2; exit 1 ;;
  esac
done

echo "==> 1/5 清空数据库"
bash "$VERIFY" clear-database.py --yes

if $INIT_ADMIN; then
  echo "==> 2/5 初始化管理员"
  bash "$VERIFY" api_verify.py init-admin
else
  echo "==> 2/5 跳过 init-admin（API 验证可直接 register）"
fi

echo "==> 3/5 注册用户"
bash "$VERIFY" api_verify.py register

echo "==> 4/5 创建 thread 并对话"
bash "$VERIFY" api_verify.py create-thread
if [[ -n "$MESSAGE" ]]; then
  bash "$VERIFY" api_verify.py chat -m "$MESSAGE"
else
  bash "$VERIFY" api_verify.py chat
fi

echo "==> 5/5 查看数据库"
bash "$VERIFY" api_verify.py inspect-db

echo
echo "完成。换用户请改 api_verify.py 的 CONFIG（email/password/cookie_file）后重新运行本脚本。"
