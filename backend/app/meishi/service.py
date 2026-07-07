"""美事回调业务逻辑：会话映射与 DeerFlow Agent 调用。"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

from app.channels.factory import make_channel_store
from app.channels.manager import (
    DEFAULT_ASSISTANT_ID,
    DEFAULT_RUN_CONFIG,
    DEFAULT_RUN_CONTEXT,
    THREAD_BUSY_MESSAGE,
    _accumulate_stream_text,
    _extract_response_text,
    _is_thread_busy_error,
    _normalize_custom_agent_name,
)
from app.channels.store import ChannelStore
from app.gateway.csrf_middleware import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token
from app.gateway.internal_auth import create_internal_auth_headers
from app.meishi.config import MeishiConfig, load_meishi_config
from app.meishi.schemas import (
    ButtonRequest,
    ButtonResponseData,
    InQARequest,
    InQAResponseData,
    MeishiApiResponse,
    MessageSyncRequest,
    PreQARequest,
    PreQAResponseData,
    WelcomeCmdItem,
    WelcomeRequest,
    WelcomeResponseData,
)
from app.meishi.sse import format_meishi_sse_chunk, format_meishi_sse_done
from app.meishi.stream_state import MeishiStreamState
from deerflow.runtime.user_context import reset_current_user, set_current_user

logger = logging.getLogger(__name__)

CHANNEL_NAME = "meishi"
_IMAGE_MSG_TYPE = "MIS:ImageMsg"


def _meishi_user_id(user_oa: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", user_oa or "unknown")
    return f"meishi:{safe}"


def _session_chat_id(sender_id: str, to_id: str) -> str:
    return sender_id or to_id or "unknown"


@asynccontextmanager
async def meishi_user_context(user_oa: str):
    user = SimpleNamespace(id=_meishi_user_id(user_oa))
    token = set_current_user(user)
    try:
        yield user
    finally:
        reset_current_user(token)


_FALLBACK_ANSWER = "抱歉，我暂时无法回答这个问题。"


def _normalize_meishi_answer(question: str, text: str) -> str:
    """Drop empty echoes of the user question; return a user-facing fallback."""
    cleaned = (text or "").strip()
    q = (question or "").strip()
    if not cleaned or cleaned == q:
        return _FALLBACK_ANSWER
    return cleaned


class MeishiAgentService:
    """将美事回调桥接到 Gateway LangGraph 运行时。"""

    def __init__(self, config: MeishiConfig | None = None, store: ChannelStore | None = None) -> None:
        self._config = config or load_meishi_config()
        self._store = store or make_channel_store()
        self._client = None
        self._csrf_token = generate_csrf_token()

    def _get_client(self):
        if self._client is None:
            from langgraph_sdk import get_client

            self._client = get_client(
                url=self._config.langgraph_url,
                headers={
                    **create_internal_auth_headers(),
                    CSRF_HEADER_NAME: self._csrf_token,
                    "Cookie": f"{CSRF_COOKIE_NAME}={self._csrf_token}",
                },
            )
        return self._client

    def _resolve_run_params(self, thread_id: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
        assistant_id = self._config.assistant_id or DEFAULT_ASSISTANT_ID
        run_config = {**DEFAULT_RUN_CONFIG, **self._config.config}
        configurable = dict(run_config.get("configurable") or {})
        configurable["checkpoint_ns"] = ""
        configurable["thread_id"] = thread_id
        run_config["configurable"] = configurable

        run_context = {
            **DEFAULT_RUN_CONTEXT,
            **self._config.context,
            "thread_id": thread_id,
        }

        if assistant_id != DEFAULT_ASSISTANT_ID:
            run_context.setdefault("agent_name", _normalize_custom_agent_name(assistant_id))
            assistant_id = DEFAULT_ASSISTANT_ID

        return assistant_id, run_config, run_context

    async def _get_or_create_thread(self, *, chat_id: str, topic_id: str | None, user_oa: str) -> str:
        thread_id = self._store.get_thread_id(CHANNEL_NAME, chat_id, topic_id=topic_id)
        if thread_id:
            return thread_id

        client = self._get_client()
        thread = await client.threads.create()
        thread_id = thread["thread_id"]
        self._store.set_thread_id(
            CHANNEL_NAME,
            chat_id,
            thread_id,
            topic_id=topic_id,
            user_id=_meishi_user_id(user_oa),
        )
        logger.info(
            "Meishi new thread: thread_id=%s chat_id=%s topic_id=%s user=%s",
            thread_id,
            chat_id,
            topic_id,
            user_oa,
        )
        return thread_id

    async def handle_pre_qa(self, body: PreQARequest) -> MeishiApiResponse:
        msg_type = (body.type or "").strip()
        if msg_type == _IMAGE_MSG_TYPE:
            return MeishiApiResponse(code=1, msg="", data=PreQAResponseData())

        data = PreQAResponseData()
        if self._config.pre_qa_scalar_map:
            data.scalar_map = dict(self._config.pre_qa_scalar_map)

        if self._config.pre_qa_prefix_user_oa and body.user_oa and body.msg:
            data.modify_msg = f"[用户 {body.user_oa}] {body.msg}"
        elif body.msg:
            data.modify_msg = body.msg

        return MeishiApiResponse(code=1, msg="", data=data.model_dump(by_alias=True, exclude_none=True))

    async def handle_in_qa_blocking(self, body: InQARequest) -> MeishiApiResponse:
        raw = await self._run_agent_once(body)
        text = _normalize_meishi_answer(body.msg or "", raw)
        data = InQAResponseData(answer=text)
        return MeishiApiResponse(code=1, msg="", data=data.model_dump(by_alias=True, exclude_none=True))

    async def stream_in_qa(self, body: InQARequest) -> AsyncIterator[bytes]:
        """生成美事问答中流式 SSE 字节流。"""
        last_sent = ""
        ack = (self._config.stream_ack_message or "").strip()
        if ack:
            yield format_meishi_sse_chunk(message=ack)
            last_sent = ack
        try:
            async for delta in self._stream_agent_deltas(body):
                if delta and delta != last_sent:
                    # 美事要求增量输出 message 字段
                    chunk = delta[len(last_sent) :] if delta.startswith(last_sent) else delta
                    if chunk:
                        yield format_meishi_sse_chunk(message=chunk)
                    last_sent = delta
        except Exception:
            logger.exception("Meishi in-QA stream failed for userOa=%s", body.user_oa)
            yield format_meishi_sse_chunk(code=500, message="服务暂时不可用，请稍后重试。")
        else:
            if not last_sent or last_sent.strip() == (body.msg or "").strip():
                logger.warning(
                    "Meishi in-QA stream produced no answer for userOa=%s (check langgraph_url, DEER_FLOW_INTERNAL_AUTH_TOKEN with workers>1, model API)",
                    body.user_oa,
                )
                yield format_meishi_sse_chunk(message=_FALLBACK_ANSWER)
        yield format_meishi_sse_done()

    def _yield_if_display_changed(
        self,
        state: MeishiStreamState,
        *,
        last_snapshot: str,
    ) -> tuple[str, str | None]:
        """若合并后的展示文案变化，返回 (new_snapshot, full_text)。"""
        snapshot = state.display_snapshot()
        if snapshot and snapshot != last_snapshot:
            return snapshot, snapshot
        return last_snapshot, None

    async def _stream_agent_deltas(self, body: InQARequest) -> AsyncIterator[str]:
        question = (body.msg or "").strip()
        if not question:
            yield "请输入您的问题。"
            return

        chat_id = _session_chat_id(body.sender_id, body.to_id)
        topic_id = body.conversation_id or None
        run_started = time.perf_counter()
        first_token_ms: int | None = None
        chunk_count = 0

        async with meishi_user_context(body.user_oa):
            thread_id = await self._get_or_create_thread(
                chat_id=chat_id,
                topic_id=topic_id,
                user_oa=body.user_oa,
            )
            thread_ready_ms = int((time.perf_counter() - run_started) * 1000)
            assistant_id, run_config, run_context = self._resolve_run_params(thread_id)
            client = self._get_client()

            streamed_buffers: dict[str, str] = {}
            current_message_id: str | None = None
            last_values: dict[str, Any] | list | None = None
            stream_state = MeishiStreamState()
            last_display = ""
            stream_modes = ["messages-tuple", "values"]

            logger.debug(
                "Meishi agent run begin: user=%s thread_id=%s topic_id=%s thread_ready_ms=%d q=%r",
                body.user_oa,
                thread_id,
                topic_id,
                thread_ready_ms,
                question[:120],
            )

            try:
                async for chunk in client.runs.stream(
                    thread_id,
                    assistant_id,
                    input={"messages": [{"role": "human", "content": question}]},
                    config=run_config,
                    context=run_context,
                    stream_mode=stream_modes,
                    multitask_strategy="reject",
                ):
                    chunk_count += 1
                    event = getattr(chunk, "event", "")
                    data = getattr(chunk, "data", None)

                    if event in ("messages-tuple", "messages"):
                        accumulated, current_message_id = _accumulate_stream_text(
                            streamed_buffers,
                            current_message_id,
                            data,
                        )
                        if accumulated:
                            stream_state.set_answer(accumulated)
                            if first_token_ms is None:
                                first_token_ms = int((time.perf_counter() - run_started) * 1000)
                            last_display, out = self._yield_if_display_changed(stream_state, last_snapshot=last_display)
                            if out:
                                yield out
                    elif event == "values" and isinstance(data, (dict, list)):
                        last_values = data
                        snapshot = _extract_response_text(data)
                        if snapshot:
                            stream_state.set_answer(snapshot)
                            if first_token_ms is None:
                                first_token_ms = int((time.perf_counter() - run_started) * 1000)
                            last_display, out = self._yield_if_display_changed(stream_state, last_snapshot=last_display)
                            if out:
                                yield out
            except Exception as exc:
                total_ms = int((time.perf_counter() - run_started) * 1000)
                logger.warning(
                    "Meishi agent run failed: user=%s thread_id=%s elapsed_ms=%d error=%s",
                    body.user_oa,
                    thread_id,
                    total_ms,
                    exc,
                )
                if _is_thread_busy_error(exc):
                    yield THREAD_BUSY_MESSAGE
                    return
                raise
            else:
                total_ms = int((time.perf_counter() - run_started) * 1000)
                logger.debug(
                    "Meishi agent run end: user=%s thread_id=%s elapsed_ms=%d first_token_ms=%s chunks=%d answer_len=%d",
                    body.user_oa,
                    thread_id,
                    total_ms,
                    first_token_ms,
                    chunk_count,
                    len(stream_state.answer_text),
                )

            if not stream_state.answer_text and last_values is not None:
                final = _extract_response_text(last_values)
                if final:
                    stream_state.set_answer(final)
                    snapshot = _normalize_meishi_answer(question, stream_state.display_snapshot())
                    if snapshot:
                        yield snapshot
            elif stream_state.display_snapshot() and stream_state.display_snapshot() != last_display:
                yield _normalize_meishi_answer(question, stream_state.display_snapshot())

    async def _run_agent_once(self, body: InQARequest) -> str:
        chunks: list[str] = []
        async for text in self._stream_agent_deltas(body):
            chunks.append(text)
        raw = chunks[-1] if chunks else ""
        return _normalize_meishi_answer(body.msg or "", raw)

    async def handle_button(self, body: ButtonRequest) -> MeishiApiResponse:
        button_id = ""
        if isinstance(body.data, dict):
            raw_id = body.data.get("id")
            if raw_id is not None:
                button_id = str(raw_id)

        prompt = f"[按钮回调 appId={body.app_id} topicId={body.topic_id} id={button_id}]"
        if body.session_id:
            prompt += f" sessionId={body.session_id}"

        in_qa = InQARequest(
            user_oa=body.user_oa,
            msg=prompt,
            sender_id=body.sender_id,
            to_id=body.to_id,
            conversation_id=body.session_id or body.topic_id,
            sign_str=body.sign_str,
            random=body.random,
            timestamp=body.timestamp,
            token=body.token,
        )

        try:
            answer = await self._run_agent_once(in_qa)
        except Exception:
            logger.exception("Meishi button callback agent error")
            answer = self._config.button_default_answer

        data = ButtonResponseData(answer=answer or self._config.button_default_answer)
        return MeishiApiResponse(code=1, msg="", data=data.model_dump(by_alias=True, exclude_none=True))

    async def handle_welcome(self, body: WelcomeRequest) -> MeishiApiResponse:
        cmd_list = [
            WelcomeCmdItem(
                text=cmd.text,
                cmd=cmd.cmd,
                actionType=cmd.action_type,
                openUrl=cmd.open_url,
            )
            for cmd in self._config.welcome_cmd_list
        ]
        data = WelcomeResponseData(
            welcomeText=self._config.welcome_text,
            cmdList=cmd_list,
            sessionExtend=body.extra or "",
        )
        return MeishiApiResponse(code=1, msg="", data=data.model_dump(by_alias=True, exclude_none=True))

    async def handle_message_sync(self, body: MessageSyncRequest) -> MeishiApiResponse:
        logger.info(
            "Meishi message sync: type=%s msgId=%s userOa=%s robotId=%s",
            body.type,
            body.msg_id,
            body.user_oa,
            body.robot_id,
        )
        return MeishiApiResponse(code=1, msg="", data={})


_meishi_service: MeishiAgentService | None = None


def get_meishi_service() -> MeishiAgentService:
    global _meishi_service
    if _meishi_service is None:
        _meishi_service = MeishiAgentService()
    return _meishi_service
