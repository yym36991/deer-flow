"""美事回调 HTTP 响应（统一 UTF-8 与 Content-Type）。"""

from __future__ import annotations

import json
from typing import Any

from starlette.responses import JSONResponse, StreamingResponse

_MEISHI_JSON_MEDIA = "application/json; charset=utf-8"
_MEISHI_SSE_MEDIA = "text/event-stream; charset=utf-8"


def meishi_json_response(payload: dict[str, Any]) -> JSONResponse:
    """JSON 响应：ensure_ascii=False + 显式 charset=utf-8（避免客户端按 Latin-1 解析）。"""
    return JSONResponse(
        content=payload,
        media_type=_MEISHI_JSON_MEDIA,
        headers={"Content-Type": _MEISHI_JSON_MEDIA},
    )


def meishi_sse_response(stream: Any) -> StreamingResponse:
    """SSE 流式响应（UTF-8）。"""
    return StreamingResponse(
        stream,
        media_type=_MEISHI_SSE_MEDIA,
        headers={
            "Content-Type": _MEISHI_SSE_MEDIA,
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


def dumps_meishi_json(payload: dict[str, Any]) -> bytes:
    """序列化为 UTF-8 JSON 字节（测试/调试用）。"""
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")
