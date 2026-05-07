"""Audit trail export + access review report — Requirement 21.7 / 22.6.

Exports every Audit_Log entry within a time window, tenant-scoped, in
JSON and CSV. The export is signed with an HMAC over the canonical
payload so a downstream auditor can verify authenticity.
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def export_audit_trail_json(
    session: Session,
    *,
    tenant_id: UUID,
    start: datetime,
    end: datetime,
) -> str:
    rows = session.execute(
        text(
            """
            SELECT id, occurred_at, actor_user_id, action, resource_type,
                   resource_id, payload, encode(prev_hash, 'hex') AS prev_hash,
                   encode(payload_hash, 'hex') AS payload_hash,
                   sequence_number
            FROM audit_log_entry
            WHERE tenant_id = :t AND occurred_at BETWEEN :s AND :e
            ORDER BY sequence_number
            """
        ),
        {"t": str(tenant_id), "s": start, "e": end},
    ).mappings().all()
    return json.dumps(
        {
            "tenant_id": str(tenant_id),
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "entry_count": len(rows),
            "entries": [
                {
                    "id": str(r["id"]),
                    "occurred_at": r["occurred_at"].isoformat(),
                    "actor_user_id": str(r["actor_user_id"]) if r["actor_user_id"] else None,
                    "action": r["action"],
                    "resource_type": r["resource_type"],
                    "resource_id": str(r["resource_id"]) if r["resource_id"] else None,
                    "payload": r["payload"],
                    "prev_hash": r["prev_hash"],
                    "payload_hash": r["payload_hash"],
                    "sequence_number": r["sequence_number"],
                }
                for r in rows
            ],
        },
        indent=2,
        default=str,
    )


def export_audit_trail_csv(
    session: Session,
    *,
    tenant_id: UUID,
    start: datetime,
    end: datetime,
) -> str:
    rows = session.execute(
        text(
            """
            SELECT occurred_at, actor_user_id, action, resource_type,
                   resource_id, payload
            FROM audit_log_entry
            WHERE tenant_id = :t AND occurred_at BETWEEN :s AND :e
            ORDER BY sequence_number
            """
        ),
        {"t": str(tenant_id), "s": start, "e": end},
    ).mappings().all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([
        "occurred_at", "actor_user_id", "action", "resource_type",
        "resource_id", "payload",
    ])
    for r in rows:
        w.writerow([
            r["occurred_at"].isoformat(),
            str(r["actor_user_id"]) if r["actor_user_id"] else "",
            r["action"],
            r["resource_type"],
            str(r["resource_id"]) if r["resource_id"] else "",
            json.dumps(r["payload"], sort_keys=True, default=str),
        ])
    return buf.getvalue()


def sign_export_hmac(payload: str, *, secret: bytes) -> str:
    return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def access_review_report(
    session: Session,
    *,
    tenant_id: UUID,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Report on every user that took an action in the window, with counts."""
    rows = session.execute(
        text(
            """
            SELECT
              actor_user_id,
              COUNT(*) AS event_count,
              COUNT(DISTINCT action) AS action_variety,
              MIN(occurred_at) AS first_event,
              MAX(occurred_at) AS last_event
            FROM audit_log_entry
            WHERE tenant_id = :t
              AND occurred_at BETWEEN :s AND :e
              AND actor_user_id IS NOT NULL
            GROUP BY actor_user_id
            ORDER BY event_count DESC
            """
        ),
        {"t": str(tenant_id), "s": start, "e": end},
    ).mappings().all()
    return [
        {
            "actor_user_id": str(r["actor_user_id"]),
            "event_count": int(r["event_count"]),
            "action_variety": int(r["action_variety"]),
            "first_event": r["first_event"].isoformat(),
            "last_event": r["last_event"].isoformat(),
        }
        for r in rows
    ]
