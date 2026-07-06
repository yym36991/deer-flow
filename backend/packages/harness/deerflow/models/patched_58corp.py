"""58 Chat Completion API adapter (chatgpt.58corp.com/api/v1).

The gateway uses OpenAI-like paths and tool calling, but streaming SSE chunks put
incremental fields under ``choices[].message`` instead of ``choices[].delta``.
Standard ``langchain_openai.ChatOpenAI`` only reads ``delta``, which yields zero
generations and breaks Agent/MCP flows.

Also preserves ``reasoning_content`` for thinking models (e.g. deepseek-r1-ali).
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Mapping
from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI
from langchain_openai.chat_models.base import _create_usage_metadata

from deerflow.models.assistant_payload_replay import restore_assistant_payloads, restore_reasoning_content

logger = logging.getLogger(__name__)

_MISSING = object()


class ChatLingAPIError(RuntimeError):
    """Raised when ChatLing returns a non-success ``code`` in the response body."""

    def __init__(self, *, code: Any, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"ChatLing API error: code={code} message={message}")


def _normalize_chatling_code(code: Any) -> int | None:
    if code is None:
        return None
    if isinstance(code, int):
        return code
    if isinstance(code, str) and code.strip().isdigit():
        return int(code.strip())
    return None


def _is_chatling_success_code(code: Any) -> bool:
    """58 ChatLing uses ``code=200`` for success in stream chunks; ``0`` also OK."""
    normalized = _normalize_chatling_code(code)
    return normalized is None or normalized in {0, 200}


def _check_chatling_api_error(payload: Mapping[str, Any]) -> None:
    code = payload.get("code")
    if _is_chatling_success_code(code):
        return
    message = payload.get("message") or payload.get("msg") or payload.get("error")
    detail = str(message or "").strip() or "unknown"
    logger.warning("ChatLing API error: code=%s message=%s", code, detail)
    raise ChatLingAPIError(code=code, message=detail)


def _guard_chatling_choices(payload: Mapping[str, Any]) -> None:
    """Raise when ChatLing returns ``code=200`` but ``choices`` is JSON null."""
    if "choices" not in payload:
        return
    choices = payload.get("choices")
    if choices is not None:
        return
    message = payload.get("message") or payload.get("msg") or payload.get("error")
    detail = str(message or "").strip() or "choices is null"
    logger.warning("ChatLing API returned null choices: code=%s message=%s", payload.get("code"), detail)
    raise ChatLingAPIError(code=payload.get("code"), message=detail)


def _coerce_chatling_payload(response: dict | Any) -> dict[str, Any] | None:
    """Normalize OpenAI SDK / dict payloads before ChatLing guards run."""
    if isinstance(response, dict):
        return response
    model_dump = getattr(response, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump(exclude={"choices": {"__all__": {"message": {"parsed"}}}})
        except TypeError:
            return model_dump()
    return None


def _inspect_chatling_response(response: dict | Any) -> None:
    payload = _coerce_chatling_payload(response)
    if payload is None:
        return
    _check_chatling_api_error(payload)
    _guard_chatling_choices(payload)


def _extract_reasoning_content(value: Any) -> str | object:
    if isinstance(value, Mapping):
        if "reasoning_content" in value and value["reasoning_content"] is not None:
            return value["reasoning_content"]
        return _MISSING

    reasoning = getattr(value, "reasoning_content", _MISSING)
    if reasoning is not _MISSING and reasoning is not None:
        return reasoning

    model_extra = getattr(value, "model_extra", None)
    if isinstance(model_extra, Mapping) and "reasoning_content" in model_extra and model_extra["reasoning_content"] is not None:
        return model_extra["reasoning_content"]

    return _MISSING


def _with_reasoning_content(message: AIMessage | AIMessageChunk, reasoning: str) -> AIMessage | AIMessageChunk:
    additional_kwargs = dict(message.additional_kwargs)
    if additional_kwargs.get("reasoning_content") != reasoning:
        additional_kwargs["reasoning_content"] = reasoning
    return message.model_copy(update={"additional_kwargs": additional_kwargs})


def _58_message_to_delta(message: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Map 58 ``choices[].message`` fields to OpenAI ``delta`` shape."""
    if not message:
        return None

    delta: dict[str, Any] = {}
    role = message.get("role")
    if role:
        delta["role"] = role

    content = message.get("content")
    if content is not None and content != "":
        delta["content"] = content

    reasoning = message.get("reasoning_content")
    if reasoning is not None and reasoning != "":
        delta["reasoning_content"] = reasoning

    tool_calls = message.get("tool_calls")
    if tool_calls:
        delta["tool_calls"] = tool_calls

    return delta or None


def normalize_58_stream_chunk(chunk: Mapping[str, Any]) -> dict[str, Any]:
    """Rewrite 58 SSE JSON so LangChain can consume ``choices[].delta``."""
    normalized = copy.deepcopy(dict(chunk))
    choices = normalized.get("choices")
    if not isinstance(choices, list):
        return normalized

    new_choices: list[dict[str, Any]] = []
    for choice in choices:
        if not isinstance(choice, Mapping):
            continue
        new_choice = dict(choice)
        if new_choice.get("delta") is None:
            delta = _58_message_to_delta(new_choice.get("message"))  # type: ignore[arg-type]
            new_choice["delta"] = delta
        new_choices.append(new_choice)

    normalized["choices"] = new_choices
    return normalized


class Patched58ChatOpenAI(ChatOpenAI):
    """ChatOpenAI for 58 ``/api/v1/chat/completions`` streaming + tools."""

    @classmethod
    def is_lc_serializable(cls) -> bool:
        return True

    @property
    def lc_secrets(self) -> dict[str, str]:
        return {"api_key": "CHATGPT_58CORP_API_KEY", "openai_api_key": "CHATGPT_58CORP_API_KEY"}

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        original_messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        restore_assistant_payloads(
            payload.get("messages", []),
            original_messages,
            restore_reasoning_content,
        )
        return payload

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
        normalized = normalize_58_stream_chunk(chunk)
        _inspect_chatling_response(normalized)
        choices = normalized.get("choices") or []
        if choices:
            choice = choices[0]
            delta = choice.get("delta")
            finish_reason = choice.get("finish_reason")
            if delta is None and finish_reason:
                token_usage = normalized.get("usage")
                usage_metadata = _create_usage_metadata(token_usage, normalized.get("service_tier")) if token_usage else None
                generation_info = dict(base_generation_info or {})
                generation_info["finish_reason"] = finish_reason
                if model_name := normalized.get("model"):
                    generation_info["model_name"] = model_name
                message = AIMessageChunk(content="", usage_metadata=usage_metadata)
                return ChatGenerationChunk(message=message, generation_info=generation_info)

        generation_chunk = super()._convert_chunk_to_generation_chunk(
            normalized,
            default_chunk_class,
            base_generation_info,
        )
        if generation_chunk is None:
            return None

        if choices:
            delta = choices[0].get("delta") or {}
            reasoning = _extract_reasoning_content(delta)
            if reasoning is not _MISSING and isinstance(generation_chunk.message, AIMessageChunk):
                generation_chunk = ChatGenerationChunk(
                    message=_with_reasoning_content(generation_chunk.message, reasoning),
                    generation_info=generation_chunk.generation_info,
                )

        return generation_chunk

    def _create_chat_result(
        self,
        response: dict | Any,
        generation_info: dict | None = None,
    ) -> ChatResult:
        _inspect_chatling_response(response)
        result = super()._create_chat_result(response, generation_info)
        response_dict = response if isinstance(response, dict) else response.model_dump()
        choices = response_dict.get("choices", [])

        patched_generations: list[ChatGeneration] | None = None
        for index, generation in enumerate(result.generations):
            if index >= len(choices):
                break
            choice_message = choices[index].get("message", {}) if isinstance(choices[index], Mapping) else {}
            reasoning = _extract_reasoning_content(choice_message)
            message = generation.message
            if reasoning is not _MISSING and isinstance(message, AIMessage):
                if patched_generations is None:
                    patched_generations = list(result.generations)
                patched_generations[index] = ChatGeneration(
                    message=_with_reasoning_content(message, reasoning),
                    generation_info=generation.generation_info,
                )

        return ChatResult(generations=patched_generations or result.generations, llm_output=result.llm_output)
