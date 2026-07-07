"""Tests for channel stream text accumulation."""

from __future__ import annotations

from app.channels.manager import _accumulate_stream_text


def test_accumulate_stream_text_skips_human_messages() -> None:
    buffers: dict[str, str] = {}
    text, msg_id = _accumulate_stream_text(
        buffers,
        None,
        {"type": "human", "content": "7月6日，请问1+1=？", "id": "human-1"},
    )
    assert text is None
    assert buffers == {}


def test_accumulate_stream_text_collects_ai_messages() -> None:
    buffers: dict[str, str] = {}
    text, msg_id = _accumulate_stream_text(
        buffers,
        None,
        {"type": "ai", "content": "1+1=2", "id": "ai-1"},
    )
    assert text == "1+1=2"
    assert msg_id == "ai-1"
