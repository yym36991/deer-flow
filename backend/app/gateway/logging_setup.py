"""Gateway 日志：stdout + wlog 滚动文件（``{base}_0.log`` 最新）。"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from app.gateway.logging_config import FileLoggingConfig, load_file_logging_config
from deerflow.logging_config import DEFAULT_LOG_DATE_FORMAT, DEFAULT_LOG_FORMAT
from wlog import WlogRollingFileHandler

# 与 meer-flow Gateway 一致：带 [LEVEL] 与源码行号，便于云主机排障。
_GATEWAY_LOG_FORMAT = "%(asctime)s - %(name)s - [%(levelname)s] - %(filename)s:%(lineno)d - %(message)s"

_configured_log_path: Path | None = None


def resolve_log_directory() -> Path:
    """解析日志目录：``DEER_FLOW_LOG_DIR`` > ``DEER_FLOW_PROJECT_ROOT/logs`` > ``cwd/logs``。"""
    import os

    explicit = os.environ.get("DEER_FLOW_LOG_DIR", "").strip()
    if explicit:
        return Path(explicit)

    project_root = os.environ.get("DEER_FLOW_PROJECT_ROOT", "").strip()
    if project_root:
        return Path(project_root) / "logs"

    return Path.cwd() / "logs"


def get_gateway_log_path() -> Path | None:
    """返回当前写入的日志文件路径（``{base}_0.log``）。"""
    return _configured_log_path


def get_gateway_log_formatter() -> logging.Formatter:
    """Gateway 滚动文件默认格式（含 [LEVEL] 与源码行号）。"""
    return logging.Formatter(_GATEWAY_LOG_FORMAT, datefmt=DEFAULT_LOG_DATE_FORMAT)


def apply_gateway_log_formatter() -> None:
    """将 Gateway 格式应用到 root 上已挂载的 handler。"""
    formatter = get_gateway_log_formatter()
    for handler in logging.root.handlers:
        handler.setFormatter(formatter)


def setup_gateway_logging(
    *,
    level: int = logging.INFO,
    file_config: FileLoggingConfig | None = None,
) -> Path | None:
    """配置 root logger：可选控制台 + wlog 滚动文件。"""
    global _configured_log_path

    cfg = file_config or load_file_logging_config()
    log_dir = resolve_log_directory()
    formatter = get_gateway_log_formatter()

    handlers: list[logging.Handler] = []

    if cfg.console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        handlers.append(console_handler)

    active_path: Path | None = None
    if cfg.enabled:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = WlogRollingFileHandler(
            log_dir,
            cfg.base_name,
            max_files=cfg.max_files,
            max_bytes=cfg.max_bytes,
        )
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)
        active_path = file_handler.active_path
        _configured_log_path = active_path

    if not handlers:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter(DEFAULT_LOG_FORMAT, datefmt=DEFAULT_LOG_DATE_FORMAT))
        handlers.append(console_handler)

    logging.basicConfig(level=level, handlers=handlers, force=True)

    init_logger = logging.getLogger(__name__)
    if active_path is not None:
        init_logger.info(
            "Gateway file logging: %s (max_files=%s, max_bytes=%s, pattern=%s_0.log.._%s.log)",
            active_path,
            cfg.max_files,
            cfg.max_bytes,
            cfg.base_name,
            cfg.max_files - 1,
        )
    elif cfg.console:
        init_logger.info("Gateway logging: console only (file_logging.enabled=false)")

    return active_path
