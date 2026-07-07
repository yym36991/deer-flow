"""``logging.Handler`` 适配 wlog 风格滚动文件。"""

from __future__ import annotations

import logging
from pathlib import Path

from wlog.rolling import WlogRollingWriter


class WlogRollingFileHandler(logging.Handler):
    """将日志写入 ``{base_name}_0.log`` … ``_{max_files-1}.log``。"""

    def __init__(
        self,
        log_dir: Path | str,
        base_name: str = "gateway",
        *,
        max_files: int = 10,
        max_bytes: int = 10 * 1024 * 1024,
        encoding: str = "utf-8",
    ) -> None:
        super().__init__()
        self.writer = WlogRollingWriter(
            log_dir,
            base_name,
            max_files=max_files,
            max_bytes=max_bytes,
            encoding=encoding,
        )
        self.active_path = self.writer.active_path

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.writer.write(msg + "\n")
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        try:
            self.writer.close()
        finally:
            super().close()
