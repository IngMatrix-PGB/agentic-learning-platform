"""Structured (JSON) logging setup using only the standard library.

No third-party logging dependency is introduced in this PR — a hand-rolled
JSON formatter is enough for "basic structured logging" and avoids pulling in
a larger API surface (e.g. structlog) before there is anything non-trivial to
log (request tracing, correlation ids, etc. come in later PRs).
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from agentic_learning_platform.config import Settings

# Uvicorn configures these three loggers itself (with its own, non-JSON
# handlers and `propagate=False`) as soon as `uvicorn.run()` starts. To make
# their output JSON too, `build_uvicorn_log_config()` strips their handlers
# and lets them propagate to the root logger instead of duplicating the
# JsonFormatter setup on a separate handler.
UVICORN_LOGGER_NAMES = ("uvicorn", "uvicorn.error", "uvicorn.access")


class JsonFormatter(logging.Formatter):
    """Render each log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info is not None:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(settings: Settings) -> None:
    """Configure the root logger to emit JSON lines to stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(settings.log_level)


def build_uvicorn_log_config(settings: Settings) -> dict[str, Any]:
    """Build a ``logging.config.dictConfig`` dict that routes uvicorn's own
    loggers through the root logger (and therefore through ``JsonFormatter``)
    instead of uvicorn's default colored/plain-text handlers.

    Deliberately does not define a ``root`` key or any ``formatters``/
    ``handlers``: it only removes uvicorn's own handlers from its three
    loggers and lets them propagate up to whatever the root logger is already
    configured with by :func:`configure_logging`. This avoids defining the
    JSON formatter a second time and avoids double emission (each logger has
    no handler of its own, so a record is only ever emitted once, by root).

    Pass as ``uvicorn.run(..., log_config=build_uvicorn_log_config(settings))``.
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "loggers": {
            name: {"handlers": [], "level": settings.log_level, "propagate": True}
            for name in UVICORN_LOGGER_NAMES
        },
    }
