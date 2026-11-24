"""Structured logging. Every line carries a ``run_id`` (CLAUDE.md conventions)."""

from __future__ import annotations

import logging
import sys
import uuid

import structlog


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def configure_logging(
    run_id: str | None = None, *, level: int = logging.INFO, json: bool = False
) -> str:
    """Configure structlog to write to stderr and bind ``run_id`` to every line. Returns it."""
    rid = run_id or new_run_id()
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=False,
    )
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(run_id=rid)
    return rid
