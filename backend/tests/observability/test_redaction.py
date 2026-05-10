"""Redaction patterns (parent R27)."""

from __future__ import annotations

import pytest

from accounting_parser.observability.redaction import redact_message


@pytest.mark.parametrize(
    "inp,expected_tokens",
    [
        ("SSN 123-45-6789 on the form", ["[REDACTED_SSN]"]),
        ("EIN is 12-3456789 per W-9", ["[REDACTED_EIN]"]),
        ("bare 9-digit 123456789 as well", ["[REDACTED_9DIGIT]"]),
        ("account 1234567890 routing", ["[REDACTED_ACCOUNT]"]),
        ("paid $12,345.67 today", ["[REDACTED_MONEY]"]),
        ("paid $75 yesterday", ["[REDACTED_MONEY]"]),
    ],
)
def test_single_pattern_redacted(inp, expected_tokens):
    out = redact_message(inp)
    for tok in expected_tokens:
        assert tok in out
    # The original sensitive substring should not survive.
    for raw in ["123-45-6789", "12-3456789", "$12,345.67", "$75", "1234567890"]:
        if raw in inp:
            assert raw not in out


def test_multiple_patterns_all_redacted():
    msg = "Client 123-45-6789 owes $45,000.00 EIN 12-3456789 account 1234567890"
    out = redact_message(msg)
    assert "[REDACTED_SSN]" in out
    assert "[REDACTED_EIN]" in out
    assert "[REDACTED_MONEY]" in out
    # Account pattern can tag either 10-digit or 9-digit first depending
    # on ordering; both redacted tokens are acceptable.
    assert "[REDACTED_ACCOUNT]" in out or "[REDACTED_9DIGIT]" in out
    assert "123-45-6789" not in out
    assert "12-3456789" not in out


def test_redaction_is_idempotent():
    msg = "SSN 123-45-6789 value $500"
    once = redact_message(msg)
    twice = redact_message(once)
    assert once == twice


def test_non_matching_strings_pass_through():
    msg = "This is a normal message with no PII"
    assert redact_message(msg) == msg


def test_short_digit_runs_not_falsely_redacted():
    """6-digit numbers (phone area codes etc.) shouldn't match the
    account pattern (which is 7-17)."""
    msg = "Room 123456 on floor 2"
    out = redact_message(msg)
    assert "123456" in out
