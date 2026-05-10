"""Audit trail export + HMAC verification — R31.2.

Produces a JSON + CSV pair of every audit_log_entry in a configurable
window, plus a separate HMAC signature bundle a regulator or counsel
can verify independently.

### HMAC signature

The signature is computed over the canonical JSON form of the
exported rows using an HMAC-SHA256 key derived from the Firm master
via ``DerivationPurpose.AUDIT_CHAIN_HMAC``. Verification only needs
the derived key + the exported bytes; no live database required.

### Why canonical JSON

HMAC-over-JSON breaks if the verifier serializes differently from
the signer. The export fixes the encoding (sorted keys, compact
separators, UTF-8) so any compliant JSON parser produces the same
byte stream to verify against.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class AuditExportBundle:
    """The three artifacts produced by an audit trail export."""

    json_bytes: bytes
    csv_bytes: bytes
    hmac_signature: bytes  # hex-encoded as bytes for easy storage


def export_audit_trail(
    rows: list[dict[str, Any]],
    *,
    hmac_key: bytes,
) -> AuditExportBundle:
    """Serialize ``rows`` to JSON + CSV + sign with HMAC-SHA256.

    Callers fetch the rows via a superuser-scoped query (RLS would
    limit to one tenant's rows — the compliance artifact is already
    tenant-scoped but the query doesn't need RLS filtering since
    the caller selects the window explicitly).

    Accepts rows as ``dict[str, Any]`` so the caller doesn't have to
    build ORM models just to export. Bytes (for prev_hash /
    payload_hash columns) are hex-encoded into the JSON; dates are
    ISO strings.
    """
    canonical_rows = [_canonicalize_row(r) for r in rows]

    json_text = json.dumps(canonical_rows, sort_keys=True, separators=(",", ":"))
    json_bytes = json_text.encode("utf-8")

    csv_buf = io.StringIO()
    if canonical_rows:
        fieldnames = sorted(canonical_rows[0].keys())
        writer = csv.DictWriter(csv_buf, fieldnames=fieldnames)
        writer.writeheader()
        for row in canonical_rows:
            writer.writerow(row)
    csv_bytes = csv_buf.getvalue().encode("utf-8")

    signature = hmac.new(hmac_key, json_bytes, hashlib.sha256).hexdigest().encode("ascii")

    return AuditExportBundle(
        json_bytes=json_bytes,
        csv_bytes=csv_bytes,
        hmac_signature=signature,
    )


def verify_audit_export(
    *,
    json_bytes: bytes,
    hmac_signature: bytes,
    hmac_key: bytes,
) -> bool:
    """Constant-time verify the export HMAC.

    Returns True iff the signature matches. ``hmac.compare_digest``
    prevents timing oracles; callers use the bool directly and never
    branch on partial matches.
    """
    expected = hmac.new(hmac_key, json_bytes, hashlib.sha256).hexdigest().encode("ascii")
    return hmac.compare_digest(expected, hmac_signature)


def _canonicalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Encode a row deterministically for JSON + CSV.

    bytes → hex, datetime → ISO, UUID → str. Recursively applied to
    nested dicts / lists.
    """
    return {k: _canonicalize_value(v) for k, v in row.items()}


def _canonicalize_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "hex") and not isinstance(value, str | bytes):
        # UUID or similar.
        try:
            return str(value)
        except Exception:  # noqa: BLE001
            return repr(value)
    if isinstance(value, dict):
        return {k: _canonicalize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_canonicalize_value(v) for v in value]
    return value
