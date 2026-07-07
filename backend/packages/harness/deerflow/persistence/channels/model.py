"""ORM model for IM channel → DeerFlow thread mappings."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class ChannelMappingRow(Base):
    """Maps an external IM conversation to a DeerFlow ``thread_id``."""

    __tablename__ = "channel_mappings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    channel_name: Mapped[str] = mapped_column(String(64), nullable=False)
    chat_id: Mapped[str] = mapped_column(String(256), nullable=False)
    # Empty string when no topic/conversation id (matches JSON store key without third segment).
    topic_id: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        UniqueConstraint("channel_name", "chat_id", "topic_id", name="uq_channel_mapping"),
        Index("ix_channel_mapping_lookup", "channel_name", "chat_id", "topic_id"),
    )
