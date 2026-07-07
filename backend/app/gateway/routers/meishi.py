"""美事（58 内部智能助手）HTTP 回调路由。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.meishi.auth import MeishiAuthError, authenticate_callback
from app.meishi.config import load_meishi_config
from app.meishi.http_response import meishi_json_response, meishi_sse_response
from app.meishi.schemas import (
    ButtonRequest,
    InQARequest,
    MeishiApiResponse,
    MessageSyncRequest,
    PreQARequest,
    WelcomeRequest,
)
from app.meishi.service import get_meishi_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meishi", tags=["meishi"])


def _ensure_enabled() -> None:
    config = load_meishi_config()
    if not config.enabled:
        raise HTTPException(status_code=503, detail="美事回调未启用，请在 config.yaml 中设置 meishi.enabled: true")


async def _auth_or_fail(model) -> None:
    config = load_meishi_config()
    if not config.secret and config.require_sign:
        raise HTTPException(status_code=503, detail="美事回调 secret 未配置")
    try:
        await authenticate_callback(model, config)
    except MeishiAuthError as exc:
        logger.warning("Meishi auth failed: %s", exc.message)
        raise HTTPException(status_code=403, detail=exc.message) from exc


@router.post("/callback/pre-qa")
async def pre_qa_callback(body: PreQARequest) -> JSONResponse:
    """问答前回调：可改写问题、设置标量或直接返回答案（非流式）。"""
    _ensure_enabled()
    await _auth_or_fail(body)
    result = await get_meishi_service().handle_pre_qa(body)
    return meishi_json_response(result.model_dump(by_alias=True, exclude_none=True))


@router.post("/callback/qa", response_model=None)
async def in_qa_callback(body: InQARequest, request: Request):
    """问答中回调：流式 SSE 调用 DeerFlow Agent（主路径）。"""
    logger.info(
        "Meishi in-QA body: userOa=%s msg_preview=%r",
        body.user_oa,
        (body.msg or "")[:80],
    )
    _ensure_enabled()
    await _auth_or_fail(body)

    accept = (request.headers.get("accept") or "").lower()
    logger.info(
        "Meishi in-QA: userOa=%s accept=%s msg_len=%d conversationId=%s",
        body.user_oa,
        accept or "(none)",
        len(body.msg or ""),
        body.conversation_id,
    )
    service = get_meishi_service()

    if "text/event-stream" in accept:
        return meishi_sse_response(service.stream_in_qa(body))

    result = await service.handle_in_qa_blocking(body)
    return meishi_json_response(result.model_dump(by_alias=True, exclude_none=True))


@router.post("/callback/button")
async def button_callback(body: ButtonRequest) -> JSONResponse:
    """按钮回调。"""
    _ensure_enabled()
    await _auth_or_fail(body)
    result = await get_meishi_service().handle_button(body)
    return meishi_json_response(result.model_dump(by_alias=True, exclude_none=True))


@router.post("/callback/welcome")
async def welcome_callback(body: WelcomeRequest) -> JSONResponse:
    """欢迎语与快捷指令回调。"""
    _ensure_enabled()
    await _auth_or_fail(body)
    result = await get_meishi_service().handle_welcome(body)
    return meishi_json_response(result.model_dump(by_alias=True, exclude_none=True))


@router.post("/callback/message-sync")
async def message_sync_callback(body: MessageSyncRequest) -> JSONResponse:
    """消息同步（图片等），仅确认接收，不返回答案。"""
    _ensure_enabled()
    await _auth_or_fail(body)
    result = await get_meishi_service().handle_message_sync(body)
    return meishi_json_response(result.model_dump(by_alias=True, exclude_none=True))


@router.get("/health")
async def meishi_health() -> JSONResponse:
    """美事回调模块健康检查（无需鉴权）。"""
    config = load_meishi_config()
    payload = MeishiApiResponse(
        code=1,
        msg="ok",
        data={"enabled": config.enabled, "app_id": config.app_id or None},
    )
    return meishi_json_response(payload.model_dump(by_alias=True, exclude_none=True))
