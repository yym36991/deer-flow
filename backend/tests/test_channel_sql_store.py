"""Tests for SQL-backed ChannelStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.channels.sql_store import SqlChannelStore


@pytest.fixture
def sql_store(tmp_path: Path) -> SqlChannelStore:
    db_path = tmp_path / "channels.db"
    return SqlChannelStore(f"sqlite:///{db_path}")


@pytest.fixture(autouse=True)
def _create_channel_tables(sql_store: SqlChannelStore):
    from deerflow.persistence.base import Base
    from deerflow.persistence.channels.model import ChannelMappingRow  # noqa: F401

    Base.metadata.create_all(sql_store._engine)


def test_sql_channel_store_roundtrip(sql_store: SqlChannelStore) -> None:
    sql_store.set_thread_id("meishi", "chat1", "thread-1", topic_id="topic-a", user_id="u1")
    assert sql_store.get_thread_id("meishi", "chat1", topic_id="topic-a") == "thread-1"
    assert sql_store.get_thread_id("meishi", "chat1") is None

    sql_store.set_thread_id("meishi", "chat1", "thread-2", topic_id="topic-a", user_id="u1")
    assert sql_store.get_thread_id("meishi", "chat1", topic_id="topic-a") == "thread-2"


def test_sql_channel_store_remove(sql_store: SqlChannelStore) -> None:
    sql_store.set_thread_id("slack", "c1", "t1")
    sql_store.set_thread_id("slack", "c1", "t2", topic_id="topic")
    assert sql_store.remove("slack", "c1", topic_id="topic") is True
    assert sql_store.get_thread_id("slack", "c1", topic_id="topic") is None
    assert sql_store.get_thread_id("slack", "c1") == "t1"
    assert sql_store.remove("slack", "c1") is True
    assert sql_store.get_thread_id("slack", "c1") is None
