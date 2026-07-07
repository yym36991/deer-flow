"""ChannelStore factory — file JSON or SQL depending on deployment."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.channels.sql_store import SqlChannelStore
from app.channels.store import ChannelStore

if TYPE_CHECKING:
    from typing import Protocol

    class ChannelStoreProtocol(Protocol):
        def get_thread_id(self, channel_name: str, chat_id: str, topic_id: str | None = None) -> str | None: ...

        def set_thread_id(
            self,
            channel_name: str,
            chat_id: str,
            thread_id: str,
            *,
            topic_id: str | None = None,
            user_id: str = "",
        ) -> None: ...

        def remove(self, channel_name: str, chat_id: str, topic_id: str | None = None) -> bool: ...

        def list_entries(self, channel_name: str | None = None) -> list: ...


logger = logging.getLogger(__name__)

_channel_store: ChannelStore | SqlChannelStore | None = None


def make_channel_store() -> ChannelStore | SqlChannelStore:
    """Return a shared ChannelStore instance.

    When ``database.backend`` is ``postgres`` (or sqlite with unified DB),
    use :class:`SqlChannelStore` so all Gateway instances share mappings.
    Otherwise fall back to the JSON file store.
    """
    global _channel_store
    if _channel_store is not None:
        return _channel_store

    from deerflow.config.app_config import get_app_config

    config = get_app_config()
    db = getattr(config, "database", None)
    backend = getattr(db, "backend", "memory") if db is not None else "memory"

    if backend in ("postgres", "sqlite") and db is not None:
        url = db.postgres_url if backend == "postgres" else f"sqlite:///{db.sqlite_path}"
        if backend == "postgres" and not url:
            logger.warning("database.backend=postgres but postgres_url empty; using file ChannelStore")
        else:
            _channel_store = SqlChannelStore(url)
            logger.info("ChannelStore backend=sql (%s)", backend)
            return _channel_store

    _channel_store = ChannelStore()
    logger.info("ChannelStore backend=file")
    return _channel_store
