#!/usr/bin/env python3
"""清空 DeerFlow PG 应用表（保留 alembic_version）。

推荐通过 verify.sh 运行（自动使用 backend 虚拟环境）:
  bash scripts/verify-api/verify.sh clear-database.py --yes
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 允许直接 python3 调用时也能找到 _paths
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _paths import load_postgres_url, resolve_config_path  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="清空 DeerFlow PG 应用表")
    parser.add_argument("--yes", "-y", action="store_true", help="跳过确认")
    args = parser.parse_args()

    try:
        config = resolve_config_path()
        url = load_postgres_url()
    except (FileNotFoundError, ValueError) as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    safe = re.sub(r":([^:@/]+)@", ":***@", url)
    print(f"配置文件: {config}")
    print(f"数据库: {safe}")

    if not args.yes:
        print("将清空除 alembic_version 外所有 public 表")
        if input("确认? [y/N] ").strip().lower() not in ("y", "yes"):
            print("已取消")
            return

    try:
        import sqlalchemy as sa
    except ImportError:
        print("错误: 需要 sqlalchemy。请用: bash scripts/verify-api/verify.sh clear-database.py --yes", file=sys.stderr)
        sys.exit(1)

    engine = sa.create_engine(url)
    with engine.connect() as conn:
        tables = [
            r[0]
            for r in conn.execute(
                sa.text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
            ).fetchall()
        ]
        targets = [t for t in tables if t != "alembic_version"]
        if not targets:
            print("无应用表（空库），跳过。")
            # 同时清理本地 cookie/state
            _clear_local_state()
            return
        conn.execute(
            sa.text(
                "TRUNCATE TABLE "
                + ", ".join(f'"{t}"' for t in targets)
                + " RESTART IDENTITY CASCADE"
            )
        )
        conn.commit()
        print(f"已清空 {len(targets)} 张表")
    _clear_local_state()


def _clear_local_state() -> None:
    from _paths import VERIFY_DIR

    if not VERIFY_DIR.exists():
        return
    removed = 0
    for p in VERIFY_DIR.glob("*"):
        if p.suffix in {".cookies"} or p.name.endswith(".state.json"):
            p.unlink(missing_ok=True)
            removed += 1
    if removed:
        print(f"已清理本地验证状态文件 {removed} 个（cookie/state）")


if __name__ == "__main__":
    main()
