"""美事问答中流式 SSE 帧格式化。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator


def format_meishi_sse_chunk(*, code: int = 200, message: str = "") -> bytes:
    payload = {"code": code, "message": message}
    return f"data:{json.dumps(payload, ensure_ascii=False)}\n\n".encode()


def format_meishi_sse_done() -> bytes:
    return b"data:[Done]\n\n"


async def iter_meishi_text_deltas(text: str, *, chunk_size: int = 32) -> AsyncIterator[bytes]:
    """将完整文本拆成增量 SSE 块（用于测试或降级）。"""
    if not text:
        yield format_meishi_sse_chunk(message="")
        yield format_meishi_sse_done()
        return

    for index in range(0, len(text), chunk_size):
        yield format_meishi_sse_chunk(message=text[index : index + chunk_size])
    yield format_meishi_sse_done()
