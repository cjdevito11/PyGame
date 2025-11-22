"""Structured logging helpers with a global LOG_LEVEL toggle."""
from __future__ import annotations

import logging
import os
from typing import Any

_LOG_FORMAT = "%(asctime)s %(name)s %(levelname)s %(message)s"
_configured = False


def configure_logging(level: str | None = None, *, force: bool = False) -> logging.Logger:
    """Configure the root logger once, honoring a LOG_LEVEL override.

    When ``force`` is True the configuration is reapplied. This makes it easy
    for tests to start with a clean slate while keeping production code simple
    and dependency-free.
    """

    global _configured

    resolved = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    log_level = getattr(logging, resolved, logging.INFO)

    if force or not _configured:
        logging.basicConfig(level=log_level, format=_LOG_FORMAT, force=force)
        _configured = True
    else:
        logging.getLogger().setLevel(log_level)

    return logging.getLogger()


def get_logger(name: str) -> logging.Logger:
    """Return a logger scoped to the provided name, configuring defaults once."""

    configure_logging()
    return logging.getLogger(name)


def format_fields(**fields: Any) -> str:
    """Render structured key/value pairs for lightweight structured logging."""

    if not fields:
        return ""
    return " | " + " ".join(f"{key}={value!r}" for key, value in sorted(fields.items()))


def log_with_fields(logger: logging.Logger, level: int, message: str, **fields: Any) -> None:
    """Log a message with an appended structured field string."""

    logger.log(level, f"{message}{format_fields(**fields)}")
