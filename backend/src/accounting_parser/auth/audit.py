"""Audit-event helpers for auth operations.

Every auth operation — login success, login failure, passkey
enrollment, session timeout, magic-link issue/consume/reject,
signup, session revocation — appends a row to ``audit_log_entry``.
The table's insert trigger computes the SHA-256 hash chain so the
sequence is tamper-evident (verified in tests in the parent Task 3
schema work).

### Action taxonomy (stable; do not rename without a migration note)

- ``auth.signup.succeeded``        — Firm_Administrator bootstrap OK
- ``auth.signup.rejected``         — refused (e.g., R25.3 second firm)
- ``auth.login.succeeded``         — session issued
- ``auth.login.failed``            — passkey assertion failed
- ``auth.session.expired``         — server-side session-timeout sweep
- ``auth.session.revoked``         — explicit logout or admin kill
- ``auth.passkey.enrollment.succeeded``
- ``auth.passkey.enrollment.failed``
- ``auth.magic_link.issued``
- ``auth.magic_link.consumed``
- ``auth.magic_link.rejected``     — unknown / expired / used

### Redaction

The audit log retains ``email`` intact because the Firm needs to
identify principals. It does NOT retain: raw passkey material, raw
tokens, request bodies, passphrases. Any route that passes through
this module has already stripped those.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


class AuthAction:
    """String constants for audit-event action names.

    Using a plain class (not Enum) so the DB column accepts the
    value directly without ``.value`` gymnastics and so callers can
    grep the codebase for the exact string that appears in logs.
    """

    SIGNUP_SUCCEEDED = "auth.signup.succeeded"
    SIGNUP_REJECTED = "auth.signup.rejected"
    LOGIN_SUCCEEDED = "auth.login.succeeded"
    LOGIN_FAILED = "auth.login.failed"
    SESSION_EXPIRED = "auth.session.expired"
    SESSION_REVOKED = "auth.session.revoked"
    PASSKEY_ENROLLMENT_SUCCEEDED = "auth.passkey.enrollment.succeeded"
    PASSKEY_ENROLLMENT_FAILED = "auth.passkey.enrollment.failed"
    MAGIC_LINK_ISSUED = "auth.magic_link.issued"
    MAGIC_LINK_CONSUMED = "auth.magic_link.consumed"
    MAGIC_LINK_REJECTED = "auth.magic_link.rejected"


def append_auth_event(
    session: Session,
    *,
    tenant_id: UUID,
    actor_user_id: UUID | None,
    action: str,
    resource_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Insert an audit_log_entry row for an auth event.

    ``payload`` is merged into a JSON blob and trimmed of any keys
    that name sensitive fields. The hash-chain trigger on the table
    does the rest.

    The row is inserted with ``resource_type='auth'`` because auth
    events span user, session, and magic-link resources — a single
    resource_type makes querying the audit trail for "all auth
    events" straightforward without a disjunction.

    This function does NOT commit; the caller's outer session commits
    so the auth event and whatever application state change (user
    row creation, session table write) are in the same transaction.
    """
    safe_payload = _scrub_payload(payload or {})
    # prev_hash / payload_hash / sequence_number are all filled in
    # by the BEFORE INSERT trigger; we set ``prev_hash`` to zeros so
    # the NOT NULL constraint is satisfied at insert time and the
    # trigger overwrites it.
    session.execute(
        text(
            """
            INSERT INTO audit_log_entry
                (tenant_id, actor_user_id, action, resource_type,
                 resource_id, payload, prev_hash, payload_hash)
            VALUES
                (:tid, :uid, :act, 'auth',
                 :rid, CAST(:payload AS jsonb),
                 '\\x0000000000000000000000000000000000000000000000000000000000000000',
                 '\\x0000000000000000000000000000000000000000000000000000000000000000')
            """
        ),
        {
            "tid": str(tenant_id),
            "uid": str(actor_user_id) if actor_user_id else None,
            "act": action,
            "rid": str(resource_id) if resource_id else None,
            "payload": _json_dumps(safe_payload),
        },
    )


_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "token",
        "raw_token",
        "jwt",
        "password",
        "passphrase",
        "credential_secret",
        "private_key",
        "signature",
        "public_key",  # Not secret but noisy; caller can re-add if needed
    }
)


def _scrub_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove keys whose names suggest sensitive contents.

    This is a defense-in-depth sweep. Routes should already be
    passing redacted payloads; this catches mistakes.
    """
    return {k: v for k, v in payload.items() if k not in _SENSITIVE_KEYS}


def _json_dumps(value: dict[str, Any]) -> str:
    """JSON-encode with sorted keys + no whitespace variance.

    Keys are sorted so hash-chain payloads are deterministic across
    runs with the same content — matches the canonical pretty-printer
    pattern established in Task 4.
    """
    import json

    # default=str handles UUID / datetime / Decimal without crashing;
    # better a stringified value in audit than a raised exception
    # that loses the audit entry entirely.
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
