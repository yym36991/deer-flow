"""Tests for Gateway file logging setup."""

from __future__ import annotations

import logging
from pathlib import Path

from app.gateway.logging_config import FileLoggingConfig, load_file_logging_config
from app.gateway.logging_setup import get_gateway_log_formatter, setup_gateway_logging


def test_load_file_logging_config_from_env(monkeypatch, tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.deploy.yaml"
    cfg_path.write_text(
        "file_logging:\n  enabled: false\n  base_name: yaml_name\n  max_files: 3\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(cfg_path))
    monkeypatch.setenv("DEER_FLOW_LOG_BASE_NAME", "env_name")
    monkeypatch.setenv("DEER_FLOW_FILE_LOG_ENABLED", "true")

    cfg = load_file_logging_config()
    assert cfg.enabled is True
    assert cfg.base_name == "env_name"
    assert cfg.max_files == 3


def test_setup_gateway_logging_writes_rolling_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DEER_FLOW_LOG_DIR", str(tmp_path))
    file_cfg = FileLoggingConfig(
        enabled=True,
        base_name="gateway",
        max_files=2,
        max_bytes=4096,
        console=False,
    )
    active = setup_gateway_logging(level=logging.INFO, file_config=file_cfg)
    assert active == tmp_path / "gateway_0.log"

    logger = logging.getLogger("test.gateway.file")
    logger.info("rolling-log-ok")
    logging.shutdown()

    assert (tmp_path / "gateway_0.log").read_text(encoding="utf-8").find("rolling-log-ok") >= 0


def test_gateway_log_formatter_includes_level_and_location() -> None:
    formatter = get_gateway_log_formatter()
    record = logging.LogRecord(
        name="app.meishi.service",
        level=logging.INFO,
        pathname=__file__,
        lineno=42,
        msg="hello",
        args=(),
        exc_info=None,
    )
    formatted = formatter.format(record)
    assert "[INFO]" in formatted
    assert "test_gateway_file_logging.py" in formatted
