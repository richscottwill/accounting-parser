"""Audit-log helpers for the auth subsystem.

Writes chained append-only entries to the Task 3 ``audit_log_entry`` table.
The hash chain is enforced by a Postgres trigger; this module supplies the
payload and actor metadata.

Audit actions emitted here:

- ``signup.tenant_bootstrap_begin`` — tenant + firm rows created
- ``signup.tenant_bootstrap_complete`` — first admin passkey registered
- ``auth.login`` — successful passkey assertion + session token issued
- ``auth.login_failed`` — any authentication failure
- ``webauthn.credential_registered`` — new passkey enrolled
- ``webauthn.credential_revoked`` — passkey removed
- ``rbac.forbidden`` — role-based-access denial at the API layer

Every entry carries tenant_id + actor_user_id + structured payload. The
schema uses ``resource_type`` / ``resource_id`` to identify what the action
is about (tenant, firm, user, webauthn_credential).
"""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def emit_audit_event(
    session: Session,
    *,
    action: str,
    tenant_id: UUID,
    resource_type: str,
    resource_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Insert an audit_log_entry.

    The Postgres trigger fills in ``prev_hash`` + ``payload_hash`` so the
    chain stays intact. Callers provide domain-meaningful payload data.

    tenant_id is REQUIRED (schema-level NOT NULL). For pre-signup events
    where no tenant exists yet, the caller should use the tenant that was
    just created as part of the same transaction.
    """
    canonical_payload = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"))
    session.execute(
        text(
            """
            INSERT INTO audit_log_entry (
                tenant_id, actor_user_id, action, resource_type,
                resource_id, payload, prev_hash, payload_hash
            )
            VALUES (
                :tenant_id, :actor_user_id, :action, :resource_type,
                :resource_id, CAST(:payload AS jsonb),
                E'\\\\x', E'\\\\x'
            )
            """
        ),
        {
            "tenant_id": str(tenant_id),
            "actor_user_id": str(actor_user_id) if actor_user_id else None,
            "action": action,
            "resource_type": resource_type,
            "resource_id": str(resource_id) if resource_id else None,
            "payload": canonical_payload,
        },
    )
