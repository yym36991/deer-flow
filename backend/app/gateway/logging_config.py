"""Gateway 文件日志配置（YAML ``file_logging`` + 环境变量）。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class FileLoggingConfig:
    enabled: bool = True
    base_name: str = "gateway"
    max_files: int = 10
    max_bytes: int = 10 * 1024 * 1024
    console: bool = True


def _parse_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _load_yaml_file_logging() -> dict[str, Any]:
    config_path = os.environ.get("DEER_FLOW_CONFIG_PATH", "").strip()
    if not config_path or not Path(config_path).is_file():
        return {}
    try:
        with open(config_path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except OSError:
        return {}
    section = raw.get("file_logging")
    return dict(section) if isinstance(section, dict) else {}


def load_file_logging_config() -> FileLoggingConfig:
    """环境变量优先，其次 ``config.deploy.yaml`` 的 ``file_logging`` 段。"""
    yaml_cfg = _load_yaml_file_logging()

    max_bytes = _parse_int(yaml_cfg.get("max_file_size_bytes"), 10 * 1024 * 1024)
    if "max_file_size_mb" in yaml_cfg:
        max_bytes = _parse_int(yaml_cfg["max_file_size_mb"], 10) * 1024 * 1024

    env_max_bytes = os.environ.get("DEER_FLOW_LOG_MAX_BYTES", "").strip()
    if env_max_bytes:
        max_bytes = _parse_int(env_max_bytes, max_bytes)

    env_max_mb = os.environ.get("DEER_FLOW_LOG_MAX_SIZE_MB", "").strip()
    if env_max_mb:
        max_bytes = _parse_int(env_max_mb, 10) * 1024 * 1024

    return FileLoggingConfig(
        enabled=_parse_bool(
            os.environ.get("DEER_FLOW_FILE_LOG_ENABLED", yaml_cfg.get("enabled", True)),
            True,
        ),
        base_name=os.environ.get("DEER_FLOW_LOG_BASE_NAME", yaml_cfg.get("base_name", "gateway")).strip() or "gateway",
        max_files=_parse_int(
            os.environ.get("DEER_FLOW_LOG_MAX_FILES", yaml_cfg.get("max_files", 10)),
            10,
        ),
        max_bytes=max_bytes,
        console=_parse_bool(
            os.environ.get("DEER_FLOW_LOG_CONSOLE", yaml_cfg.get("console", True)),
            True,
        ),
    )
