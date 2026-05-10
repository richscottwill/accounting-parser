"""LogSinkAdapter + structlog configuration.

Production logs flow to stdout as JSON (structlog's JSON renderer)
then promtail ships them to Loki. ``LokiLogAdapter`` is a stdout
shim that applies redaction before emission.

Tests get ``NullLogSinkAdapter`` which keeps the last N emitted
records in memory for assertion.
"""

from __future__ import annotations

import logging
import sys
from collections import deque
from typing import Any, Protocol

from accounting_parser.observability.redaction import redact_message


class LogSinkAdapter(Protocol):
    """Contract every log-sink backend satisfies."""

    provider: str

    def emit(self, level: str, message: str, **context: Any) -> None: ...


class NullLogSinkAdapter(LogSinkAdapter):
    """Captures the most recent N log records for test assertions."""

    provider: str = "null"

    def __init__(self, *, ring_size: int = 512) -> None:
        self.records: deque[dict[str, Any]] = deque(maxlen=ring_size)

    def emit(self, level: str, message: str, **context: Any) -> None:
        redacted = redact_message(message)
        self.records.append({"level": level, "message": redacted, **context})


class LokiLogAdapter(LogSinkAdapter):
    """Writes redacted JSON log lines to stdout for promtail pickup."""

    provider: str = "loki"

    def __init__(self, *, logger_name: str = "accounting_parser") -> None:
        self._logger = logging.getLogger(logger_name)

    def emit(self, level: str, message: str, **context: Any) -> None:
        redacted = redact_message(message)
        level_no = getattr(logging, level.upper(), logging.INFO)
        self._logger.log(level_no, redacted, extra={"context": context})


def configure_structured_logging(
    *,
    level: str = "INFO",
    enable_redaction: bool = True,
) -> None:
    """Install a minimal JSON formatter on the root logger.

    Idempotent: calling twice replaces the handler. Adds a
    redaction filter that rewrites ``LogRecord.msg`` through the
    parent R27 pattern set before any handler sees it. Disable only
    in unit tests that assert specific unredacted strings — never
    in production.
    """
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    formatter = _JsonFormatter()
    handler.setFormatter(formatter)
    if enable_redaction:
        handler.addFilter(_RedactionFilter())
    root.addHandler(handler)


class _RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_message(record.msg)
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        import json

        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
        }
        context = getattr(record, "context", None)
        if isinstance(context, dict):
            payload["context"] = context
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, sort_keys=True)
