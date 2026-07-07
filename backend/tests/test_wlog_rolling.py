"""Tests for wlog-style rolling log files."""

from __future__ import annotations

import logging

import pytest

from wlog.handler import WlogRollingFileHandler
from wlog.rolling import WlogRollingWriter


def test_rotate_shifts_indices_and_drops_oldest(tmp_path) -> None:
    writer = WlogRollingWriter(tmp_path, "gateway", max_files=3, max_bytes=20)
    writer.write("a" * 15)
    writer.write("b" * 15)
    writer.close()

    assert (tmp_path / "gateway_0.log").exists()
    assert (tmp_path / "gateway_1.log").exists()
    assert not (tmp_path / "gateway_2.log").exists()

    writer2 = WlogRollingWriter(tmp_path, "gateway", max_files=3, max_bytes=20)
    writer2.write("c" * 15)
    writer2.close()

    assert (tmp_path / "gateway_0.log").read_text(encoding="utf-8") == "c" * 15
    assert (tmp_path / "gateway_2.log").exists()
    assert not (tmp_path / "gateway_3.log").exists()


def test_handler_writes_formatted_records(tmp_path) -> None:
    handler = WlogRollingFileHandler(tmp_path, "app", max_files=2, max_bytes=1024)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("test.wlog.handler")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    logger.info("hello-中文")
    handler.close()

    content = (tmp_path / "app_0.log").read_text(encoding="utf-8")
    assert "hello-中文" in content


def test_invalid_max_files() -> None:
    with pytest.raises(ValueError):
        WlogRollingWriter(".", "x", max_files=0, max_bytes=100)
