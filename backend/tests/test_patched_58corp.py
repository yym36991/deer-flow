"""Tests for deerflow.models.patched_58corp."""

from __future__ import annotations

from langchain_core.messages import AIMessageChunk

from deerflow.models.patched_58corp import (
    Patched58ChatOpenAI,
    _58_message_to_delta,
    normalize_58_stream_chunk,
)


def test_message_to_delta_text_stream_piece():
    delta = _58_message_to_delta({"role": "assistant", "content": "你好"})
    assert delta == {"role": "assistant", "content": "你好"}


def test_message_to_delta_reasoning_piece():
    delta = _58_message_to_delta({"role": "assistant", "content": "", "reasoning_content": "好的"})
    assert delta == {"role": "assistant", "reasoning_content": "好的"}


def test_message_to_delta_tool_call_first_piece():
    delta = _58_message_to_delta(
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "index": 0,
                    "id": "call_abc",
                    "type": "function",
                    "function": {"name": "deerflow_demo_add_numbers", "arguments": ""},
                }
            ],
        }
    )
    assert delta is not None
    assert delta["tool_calls"][0]["function"]["name"] == "deerflow_demo_add_numbers"


def test_normalize_stream_chunk_moves_message_to_delta():
    raw = {
        "code": 200,
        "choices": [
            {
                "index": 0,
                "finish_reason": None,
                "message": {"role": "assistant", "content": "，"},
            }
        ],
    }
    normalized = normalize_58_stream_chunk(raw)
    assert normalized["choices"][0]["delta"]["content"] == "，"
    assert "message" in normalized["choices"][0]


def test_chatling_success_code_200_is_not_error():
    from deerflow.models.patched_58corp import _check_chatling_api_error

    _check_chatling_api_error({"code": 200, "message": "成功"})


def test_chatling_error_code_raises():
    import pytest

    from deerflow.models.patched_58corp import ChatLingAPIError, _check_chatling_api_error

    with pytest.raises(ChatLingAPIError, match="508"):
        _check_chatling_api_error({"code": 508, "message": "Api请求异常"})


def test_null_choices_raises_even_when_code_200():
    import pytest

    from deerflow.models.patched_58corp import ChatLingAPIError, _guard_chatling_choices

    with pytest.raises(ChatLingAPIError, match="成功"):
        _guard_chatling_choices({"code": 200, "message": "成功", "choices": None})
    with pytest.raises(ChatLingAPIError, match="QPM"):
        _guard_chatling_choices({"code": 510, "message": "QPM limit", "choices": None})


def test_create_chat_result_guards_pydantic_null_choices():
    import pytest
    from openai.types.chat import ChatCompletion

    from deerflow.models.patched_58corp import ChatLingAPIError, Patched58ChatOpenAI

    model = Patched58ChatOpenAI(model="chatling-plus", api_key="test-key", base_url="https://example.com/api/v1")
    response = ChatCompletion.model_construct(
        id="x",
        choices=None,
        created=1,
        model="chatling-plus",
        object="chat.completion",
        code=200,
        message="成功",
    )
    with pytest.raises(ChatLingAPIError, match="成功"):
        model._create_chat_result(response)


def test_convert_chunk_text_stream():
    model = Patched58ChatOpenAI(model="chatling-plus", api_key="test-key", base_url="https://example.com/api/v1")
    chunk = normalize_58_stream_chunk(
        {
            "model": "chatling-plus",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "你好"}}],
        }
    )
    generation_chunk = model._convert_chunk_to_generation_chunk(chunk, AIMessageChunk, {})
    assert generation_chunk is not None
    assert generation_chunk.message.content == "你好"


def test_convert_chunk_finish_reason_only():
    model = Patched58ChatOpenAI(model="chatling-plus", api_key="test-key", base_url="https://example.com/api/v1")
    chunk = normalize_58_stream_chunk(
        {
            "model": "chatling-plus",
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        }
    )
    generation_chunk = model._convert_chunk_to_generation_chunk(chunk, AIMessageChunk, {})
    assert generation_chunk is not None
    assert generation_chunk.generation_info is not None
    assert generation_chunk.generation_info.get("finish_reason") == "tool_calls"


def test_convert_chunk_tool_call_stream():
    model = Patched58ChatOpenAI(model="chatling-plus", api_key="test-key", base_url="https://example.com/api/v1")
    chunk = normalize_58_stream_chunk(
        {
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "index": 0,
                                "type": "function",
                                "function": {"arguments": '{"city": "'},
                            }
                        ],
                    },
                }
            ]
        }
    )
    generation_chunk = model._convert_chunk_to_generation_chunk(chunk, AIMessageChunk, {})
    assert generation_chunk is not None
    tool_chunks = generation_chunk.message.tool_call_chunks
    assert tool_chunks
    assert tool_chunks[0]["args"] == '{"city": "'
