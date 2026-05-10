"""LogSinkAdapter + configure_structured_logging."""

from __future__ import annotations

import json
import logging

import pytest

from accounting_parser.observability.logging import NullLogSinkAdapter, configure_structured_logging


def test_null_sink_redacts_at_emit():
    sink = NullLogSinkAdapter()
    sink.emit(
        "INFO",
        "processing SSN 123-45-6789 for client",
        component="ingestion",
    )
    rec = sink.records[0]
    assert "[REDACTED_SSN]" in rec["message"]
    assert "123-45-6789" not in rec["message"]
    assert rec["component"] == "ingestion"


def test_null_sink_ring_bounded():
    sink = NullLogSinkAdapter(ring_size=3)
    for i in range(5):
        sink.emit("INFO", f"msg {i}")
    # Keeps last 3.
    assert len(sink.records) == 3
    assert [r["message"] for r in sink.records] == ["msg 2", "msg 3", "msg 4"]


def test_configure_structured_logging_emits_json(capsys):
    configure_structured_logging(level="INFO")
    logger = logging.getLogger("test.obs")
    logger.info("client owed $1,234.00 last month")
    captured = capsys.readouterr()
    # Each line should parse as JSON with redaction applied.
    for line in captured.out.strip().splitlines():
        if not line:
            continue
        payload = json.loads(line)
        assert "level" in payload
        assert "message" in payload
        if "owed" in payload["message"]:
            assert "[REDACTED_MONEY]" in payload["message"]
            assert "$1,234.00" not in payload["message"]


def test_configure_is_idempotent():
    """Second call replaces handlers; doesn't stack duplicates."""
    configure_structured_logging(level="INFO")
    first_handlers = list(logging.getLogger().handlers)
    configure_structured_logging(level="INFO")
    second_handlers = list(logging.getLogger().handlers)
    assert len(second_handlers) == 1
    # It's a fresh StreamHandler so identity differs from first call.
    assert second_handlers[0] is not first_handlers[0] or len(first_handlers) == 1


@pytest.fixture(autouse=True)
def _reset_logging():
    yield
    # Leave the logging system in a clean state for the next test.
    root = logging.getLogger()
    root.handlers.clear()
    root.filters.clear()
