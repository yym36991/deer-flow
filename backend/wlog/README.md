# wlog（Python）

按大小滚动文件语义，文件名为 **`{base_name}_0.log`（最新）** … **`_{N-1}.log`（最旧）**。

## 用法

```python
import logging
from wlog import WlogRollingFileHandler

handler = WlogRollingFileHandler(
    "/opt/deer-flow/logs",
    "gateway",
    max_files=10,
    max_bytes=10 * 1024 * 1024,
)
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logging.root.addHandler(handler)
```

Gateway 已在 `app/gateway/logging_setup.py` 中集成；配置见 `config.deploy.yaml` 的 `file_logging`。

## Python 标准库对比

| 方案 | 命名 | 说明 |
|------|------|------|
| `RotatingFileHandler` | `app.log`, `app.log.1` | 后缀递增，**最新常为无编号主文件**，与 wlog 相反 |
| `TimedRotatingFileHandler` | 按时间 | 不按大小 |
| `concurrent-log-handler` | 多进程 | 仍非 `_0` 最新语义 |

本库用于与现有 Go 服务/运维习惯一致。
