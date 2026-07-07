"""记录所有到达 Gateway 的美事 HTTP 请求（含鉴权失败前的入口）。"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


class MeishiAccessLogMiddleware(BaseHTTPMiddleware):
    """在美事路由处理前记录 method/path/来源 IP 与响应状态码。"""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if not path.startswith("/api/meishi"):
            return await call_next(request)

        client_host = request.client.host if request.client else "unknown"
        logger.info(
            "Meishi HTTP begin: %s %s from %s accept=%s",
            request.method,
            path,
            client_host,
            request.headers.get("accept", ""),
        )
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        logger.debug(
            "Meishi HTTP end: %s %s -> %s elapsed_ms=%d",
            request.method,
            path,
            response.status_code,
            elapsed_ms,
        )
        logger.info(
            "Meishi HTTP end: %s %s -> %s",
            request.method,
            path,
            response.status_code,
        )
        return response
