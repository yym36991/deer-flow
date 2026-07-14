"""Shared paths for verify-api scripts."""

from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERIFY_DIR = ROOT / ".deer-flow" / "verify-api"


def resolve_config_path() -> Path:
    env = os.environ.get("DEER_FLOW_CONFIG_PATH")
    if env:
        p = Path(env)
        if p.is_file():
            return p
    default = ROOT / "config.yaml"
    if default.is_file():
        return default
    raise FileNotFoundError(f"未找到 config.yaml（已查 DEER_FLOW_CONFIG_PATH 与 {default}）")


def load_postgres_url() -> str:
    text = resolve_config_path().read_text(encoding="utf-8")
    m = re.search(r"^\s*postgres_url:\s*(\S+)\s*$", text, re.MULTILINE)
    if not m:
        raise ValueError("config.yaml 中未找到 database.postgres_url")
    url = m.group(1).strip().strip("'\"")
    if url.startswith("$"):
        raise ValueError(f"postgres_url 为占位符 {url}，请改为实际连接串")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("postgresql+psycopg://"):
        return url
    raise ValueError("仅支持 postgresql:// 连接串")
