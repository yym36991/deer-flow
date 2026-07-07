"""wlog 风格滚动日志库（``{base}_0.log`` 为最新）。"""

from wlog.handler import WlogRollingFileHandler
from wlog.rolling import WlogRollingWriter

__all__ = ["WlogRollingFileHandler", "WlogRollingWriter"]
