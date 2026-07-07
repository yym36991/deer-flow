"""滚动文件写入器，语义对齐 Go ``wlog.NewRollingFile``。

文件命名：``{base_name}_0.log``（当前写入）… ``{base_name}_{max_files-1}.log``（最旧）。
轮转时：删除 ``_{max-1}``，``_{i}`` → ``_{i+1}``（``i`` 从 ``max-2`` 到 ``0``），新建 ``_0``。
"""

from __future__ import annotations

import os
import threading
from pathlib import Path


class WlogRollingWriter:
    """线程安全的按大小滚动文件写入器。"""

    def __init__(
        self,
        log_dir: os.PathLike[str] | str,
        base_name: str,
        *,
        max_files: int = 10,
        max_bytes: int = 10 * 1024 * 1024,
        encoding: str = "utf-8",
    ) -> None:
        if max_files <= 0:
            raise ValueError(f"max_files must be positive, got {max_files}")
        if max_bytes <= 0:
            raise ValueError(f"max_bytes must be positive, got {max_bytes}")
        if not base_name or "/" in base_name or "\\" in base_name:
            raise ValueError(f"invalid base_name: {base_name!r}")

        self.log_dir = Path(log_dir)
        self.base_name = base_name
        self.max_files = max_files
        self.max_bytes = max_bytes
        self.encoding = encoding

        self._lock = threading.RLock()
        self._file = None
        self._frag_size = 0
        self._closed = False

        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._roll_if_needed(force_open=True)

    @property
    def active_path(self) -> Path:
        """当前写入文件（``_0``）。"""
        return self._path(0)

    def _path(self, index: int) -> Path:
        return self.log_dir / f"{self.base_name}_{index}.log"

    def _rotate_names(self) -> None:
        """与 Go ``rollingFile.rollingName`` 一致：删最旧，依次后移。"""
        last = self.max_files - 1
        oldest = self._path(last)
        if oldest.exists():
            oldest.unlink()

        for i in range(last - 1, -1, -1):
            src = self._path(i)
            dst = self._path(i + 1)
            if src.exists():
                src.replace(dst)

    def _close_file(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def _open_active(self) -> None:
        path = self._path(0)
        self._file = open(path, "a", encoding=self.encoding)
        self._frag_size = path.stat().st_size if path.exists() else 0

    def _roll_if_needed(self, *, force_open: bool = False) -> None:
        rolling = False

        if self._file is not None:
            if self._frag_size < self.max_bytes:
                return
            self._close_file()
            self._frag_size = 0
            rolling = True
        else:
            path = self._path(0)
            if path.exists():
                size = path.stat().st_size
                if size < self.max_bytes:
                    self._frag_size = size
                else:
                    self._frag_size = 0
                    rolling = True
            elif force_open:
                rolling = False

        if rolling:
            self._rotate_names()

        if self._file is None:
            self._open_active()

    def write(self, data: bytes | str) -> int:
        if isinstance(data, bytes):
            text = data.decode(self.encoding)
        else:
            text = data
        if not text:
            return 0

        with self._lock:
            if self._closed:
                raise ValueError("WlogRollingWriter is closed")

            self._roll_if_needed()

            byte_len = len(text.encode(self.encoding))
            if self._frag_size + byte_len > self.max_bytes and self._frag_size > 0:
                self._close_file()
                self._frag_size = 0
                self._rotate_names()
                self._open_active()

            assert self._file is not None
            n = self._file.write(text)
            self._frag_size += byte_len
            self._file.flush()
            return n

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._close_file()
