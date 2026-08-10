"""Structured logging.

One JSON object per line so Cloud Run / Loki can parse it without a shipper
config. A ``request_id`` and ``thread_id`` bound per request travel with every
log record through a contextvar - no plumbing through call signatures.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

_context: ContextVar[dict[str, Any]] = ContextVar("log_context", default={})

_RESERVED = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name",
    "pathname", "process", "processName", "relativeCreated", "stack_info",
    "thread", "threadName", "taskName",
}


def bind(**kwargs: Any) -> None:
    """Attach key/values to every subsequent log record in this context."""
    _context.set({**_context.get(), **{k: v for k, v in kwargs.items() if v is not None}})


def clear() -> None:
    _context.set({})


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(_context.get())
        payload.update({k: v for k, v in record.__dict__.items() if k not in _RESERVED})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ctx = _context.get()
        suffix = " " + " ".join(f"{k}={v}" for k, v in ctx.items()) if ctx else ""
        return f"{record.levelname:<7} {record.name}: {record.getMessage()}{suffix}"


def configure(level: str = "INFO", json_output: bool = True) -> None:
    """Idempotent root-logger setup."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_output else PlainFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # These are chatty at INFO and add nothing over our own request logs.
    for noisy in ("httpx", "httpcore", "openai", "psycopg.pool"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
