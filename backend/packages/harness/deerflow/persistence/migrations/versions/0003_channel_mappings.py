"""Add ``channel_mappings`` table for IM / Meishi thread mapping.

Revision ID: 0003_channel_mappings
Revises: 0002_runs_token_usage
Create Date: 2026-07-06

Stores external conversation keys (channel + chat + optional topic) mapped to
LangGraph ``thread_id`` values. Used by :class:`app.channels.sql_store.SqlChannelStore`
so multi-instance Gateway deployments share Meishi session state.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_channel_mappings"
down_revision: str | Sequence[str] | None = "0002_runs_token_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "channel_mappings" in insp.get_table_names():
        return

    op.create_table(
        "channel_mappings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("channel_name", sa.String(length=64), nullable=False),
        sa.Column("chat_id", sa.String(length=256), nullable=False),
        sa.Column("topic_id", sa.String(length=256), nullable=False),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("channel_name", "chat_id", "topic_id", name="uq_channel_mapping"),
    )
    with op.batch_alter_table("channel_mappings", schema=None) as batch_op:
        batch_op.create_index("ix_channel_mapping_lookup", ["channel_name", "chat_id", "topic_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("channel_mappings", schema=None) as batch_op:
        batch_op.drop_index("ix_channel_mapping_lookup")
    op.drop_table("channel_mappings")
