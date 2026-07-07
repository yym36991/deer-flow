"""SQL-backed ChannelStore for multi-instance Gateway deployments."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from deerflow.persistence.channels.model import ChannelMappingRow

logger = logging.getLogger(__name__)


def to_sync_sqlalchemy_url(url: str) -> str:
    """Convert async SQLAlchemy / libpq URLs to a sync driver URL."""
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("sqlite+aiosqlite:///"):
        return url.replace("sqlite+aiosqlite:///", "sqlite:///", 1)
    return url


def _normalize_topic_id(topic_id: str | None) -> str:
    return topic_id or ""


class SqlChannelStore:
    """PostgreSQL/SQLite-backed channel mapping store.

    Uses a synchronous SQLAlchemy engine so existing sync call sites
    (``ChannelManager``, ``MeishiAgentService``) do not need refactors.
    Tables are created by ``init_engine()`` at Gateway startup.
    """

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("SqlChannelStore requires a non-empty database URL")
        sync_url = to_sync_sqlalchemy_url(database_url)
        self._engine: Engine = create_engine(sync_url, pool_pre_ping=True)
        logger.info("SqlChannelStore initialised (sync driver)")

    @staticmethod
    def _row_to_entry(row: ChannelMappingRow) -> dict[str, Any]:
        item: dict[str, Any] = {
            "channel_name": row.channel_name,
            "chat_id": row.chat_id,
            "thread_id": row.thread_id,
            "user_id": row.user_id or "",
            "created_at": row.created_at.timestamp() if row.created_at else 0.0,
            "updated_at": row.updated_at.timestamp() if row.updated_at else 0.0,
        }
        if row.topic_id:
            item["topic_id"] = row.topic_id
        return item

    def get_thread_id(self, channel_name: str, chat_id: str, topic_id: str | None = None) -> str | None:
        topic = _normalize_topic_id(topic_id)
        with Session(self._engine) as session:
            row = session.execute(
                select(ChannelMappingRow).where(
                    ChannelMappingRow.channel_name == channel_name,
                    ChannelMappingRow.chat_id == chat_id,
                    ChannelMappingRow.topic_id == topic,
                )
            ).scalar_one_or_none()
            return row.thread_id if row else None

    def set_thread_id(
        self,
        channel_name: str,
        chat_id: str,
        thread_id: str,
        *,
        topic_id: str | None = None,
        user_id: str = "",
    ) -> None:
        topic = _normalize_topic_id(topic_id)
        now = datetime.now(UTC)
        with Session(self._engine) as session:
            row = session.execute(
                select(ChannelMappingRow).where(
                    ChannelMappingRow.channel_name == channel_name,
                    ChannelMappingRow.chat_id == chat_id,
                    ChannelMappingRow.topic_id == topic,
                )
            ).scalar_one_or_none()
            if row is None:
                session.add(
                    ChannelMappingRow(
                        channel_name=channel_name,
                        chat_id=chat_id,
                        topic_id=topic,
                        thread_id=thread_id,
                        user_id=user_id,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                row.thread_id = thread_id
                row.user_id = user_id
                row.updated_at = now
            session.commit()

    def remove(self, channel_name: str, chat_id: str, topic_id: str | None = None) -> bool:
        topic = _normalize_topic_id(topic_id)
        with Session(self._engine) as session:
            if topic_id is not None:
                result = session.execute(
                    delete(ChannelMappingRow).where(
                        ChannelMappingRow.channel_name == channel_name,
                        ChannelMappingRow.chat_id == chat_id,
                        ChannelMappingRow.topic_id == topic,
                    )
                )
                session.commit()
                return (result.rowcount or 0) > 0

            result = session.execute(
                delete(ChannelMappingRow).where(
                    ChannelMappingRow.channel_name == channel_name,
                    ChannelMappingRow.chat_id == chat_id,
                )
            )
            session.commit()
            return (result.rowcount or 0) > 0

    def list_entries(self, channel_name: str | None = None) -> list[dict[str, Any]]:
        with Session(self._engine) as session:
            stmt = select(ChannelMappingRow)
            if channel_name:
                stmt = stmt.where(ChannelMappingRow.channel_name == channel_name)
            rows = session.execute(stmt.order_by(ChannelMappingRow.id)).scalars().all()
            return [self._row_to_entry(row) for row in rows]
