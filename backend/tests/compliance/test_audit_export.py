"""Audit trail export + HMAC verification (R31.2)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from accounting_parser.compliance.audit_export import export_audit_trail, verify_audit_export


def _row(action: str, ts: datetime) -> dict:
    return {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "actor_user_id": uuid4(),
        "action": action,
        "resource_type": "test",
        "resource_id": uuid4(),
        "payload": {"note": "hello"},
        "prev_hash": b"\x00" * 32,
        "payload_hash": b"\xaa" * 32,
        "sequence_number": 1,
        "occurred_at": ts,
    }


def test_export_json_is_canonical():
    rows = [_row("auth.signup.succeeded", datetime(2026, 5, 10, 12, tzinfo=UTC))]
    bundle = export_audit_trail(rows, hmac_key=b"test-key-32-bytes-00000000000000")
    # Canonical JSON sorts keys + uses compact separators.
    text = bundle.json_bytes.decode("utf-8")
    assert '"action":"auth.signup.succeeded"' in text
    assert ": " not in text  # compact separators
    # Bytes converted to hex.
    assert "00" * 32 in text  # prev_hash


def test_export_csv_has_header_and_sorted_columns():
    rows = [_row("x", datetime(2026, 5, 10, tzinfo=UTC))]
    bundle = export_audit_trail(rows, hmac_key=b"k" * 32)
    lines = bundle.csv_bytes.decode("utf-8").strip().splitlines()
    assert len(lines) == 2  # header + 1 row
    headers = lines[0].split(",")
    assert headers == sorted(headers)  # alpha-sorted
    assert "action" in headers


def test_hmac_verifies_with_correct_key():
    rows = [_row("x", datetime(2026, 5, 10, tzinfo=UTC))]
    key = b"x" * 32
    bundle = export_audit_trail(rows, hmac_key=key)
    assert (
        verify_audit_export(
            json_bytes=bundle.json_bytes,
            hmac_signature=bundle.hmac_signature,
            hmac_key=key,
        )
        is True
    )


def test_hmac_fails_with_wrong_key():
    rows = [_row("x", datetime(2026, 5, 10, tzinfo=UTC))]
    bundle = export_audit_trail(rows, hmac_key=b"right-key-padding-to-32-bytes---")
    assert (
        verify_audit_export(
            json_bytes=bundle.json_bytes,
            hmac_signature=bundle.hmac_signature,
            hmac_key=b"wrong-key-padding-to-32-bytes---",
        )
        is False
    )


def test_hmac_fails_on_tampered_json():
    rows = [_row("x", datetime(2026, 5, 10, tzinfo=UTC))]
    key = b"k" * 32
    bundle = export_audit_trail(rows, hmac_key=key)
    # Flip a byte in the middle of the JSON.
    tampered = bytearray(bundle.json_bytes)
    tampered[len(tampered) // 2] ^= 0xFF
    assert (
        verify_audit_export(
            json_bytes=bytes(tampered),
            hmac_signature=bundle.hmac_signature,
            hmac_key=key,
        )
        is False
    )


def test_empty_rows_still_produces_valid_bundle():
    bundle = export_audit_trail([], hmac_key=b"k" * 32)
    assert json.loads(bundle.json_bytes.decode()) == []
    assert verify_audit_export(
        json_bytes=bundle.json_bytes,
        hmac_signature=bundle.hmac_signature,
        hmac_key=b"k" * 32,
    )
