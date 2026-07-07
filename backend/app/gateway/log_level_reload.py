"""Reload ``log_level`` from config on SIGUSR1 (``kill -USR1 <pid>`` / ``kill -10 <pid>``)."""

from __future__ import annotations

import logging
import signal
import threading
from typing import Any

from deerflow.config.app_config import apply_logging_level, reload_app_config

logger = logging.getLogger(__name__)

_LOG_RELOAD_SIGNAL = getattr(signal, "SIGUSR1", None)
_registered = False
_previous_handler: Any = None


def reload_logging_level_from_config() -> str:
    """Re-read config file and apply ``log_level`` to ``deerflow`` / ``app`` loggers."""
    config = reload_app_config()
    apply_logging_level(config.log_level)
    return config.log_level


def _handle_log_reload_signal(signum: int, _frame: Any) -> None:
    try:
        level_name = reload_logging_level_from_config()
        logger.info(
            "log_level reloaded from config after signal %s (%s)",
            signum,
            level_name,
        )
    except Exception:
        logger.exception("Failed to reload log_level after signal %s", signum)


def register_log_level_reload_signal() -> bool:
    """Register SIGUSR1 handler once per process. Returns True if registered."""
    global _registered, _previous_handler

    if _registered or _LOG_RELOAD_SIGNAL is None:
        return False

    if threading.current_thread() is not threading.main_thread():
        return False

    _previous_handler = signal.signal(_LOG_RELOAD_SIGNAL, _handle_log_reload_signal)
    _registered = True
    logger.info(
        "log_level hot-reload enabled: edit config log_level then run 'kill -USR1 <pid>' or 'kill -10 <pid>' (use uvicorn worker PID, not service name)",
    )
    return True


def unregister_log_level_reload_signal() -> None:
    """Restore previous SIGUSR1 handler (lifespan shutdown)."""
    global _registered, _previous_handler

    if not _registered or _LOG_RELOAD_SIGNAL is None:
        return

    if _previous_handler is not None:
        signal.signal(_LOG_RELOAD_SIGNAL, _previous_handler)
    _registered = False
    _previous_handler = None
