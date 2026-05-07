"""PBC (Prepared-By-Client) request lifecycle.

Implements Requirement 16 state machine at the service layer. The HTTP
routes sit in ``portal/routes.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from accounting_parser.auth.audit import emit_audit_event


class PBCStatus(str, Enum):
    NOT_REQUESTED = "not_requested"
    REQUESTED = "requested"
    IN_PROGRESS = "in_progress"
    RECEIVED = "received"
    UNDER_REVIEW = "under_review"
    ACCEPTED = "accepted"
    REJECTED_RESUBMIT = "rejected_resubmit"
    WAIVED = "waived"
    OPEN = "open"
    SENT = "sent"
    CLOSED = "closed"


# Allowed transitions. Values match the Task 3 pbc_request CHECK constraint:
#   open, sent, in_progress, received, closed, waived
# We map the richer UI states onto those six storage states — the UI
# surfaces the richer vocabulary without changing the DB enum.
_TRANSITIONS: dict[PBCStatus, set[PBCStatus]] = {
    PBCStatus.OPEN: {PBCStatus.SENT, PBCStatus.CLOSED, PBCStatus.WAIVED},
    PBCStatus.SENT: {PBCStatus.IN_PROGRESS, PBCStatus.RECEIVED, PBCStatus.CLOSED, PBCStatus.WAIVED},
    PBCStatus.IN_PROGRESS: {PBCStatus.RECEIVED, PBCStatus.CLOSED, PBCStatus.WAIVED},
    PBCStatus.RECEIVED: {PBCStatus.IN_PROGRESS, PBCStatus.CLOSED},
    PBCStatus.CLOSED: set(),
    PBCStatus.WAIVED: set(),
}


class InvalidPBCTransition(Exception):
    pass


def can_transition(from_: PBCStatus, to: PBCStatus) -> bool:
    return to in _TRANSITIONS.get(from_, set())


@dataclass
class PBCCreateRequest:
    engagement_id: UUID
    title: str
    description: str | None = None
    assigned_preparer_id: UUID | None = None
    due_at: str | None = None  # YYYY-MM-DD


def create_pbc_request(
    session: Session,
    *,
    tenant_id: UUID,
    actor_user_id: UUID,
    req: PBCCreateRequest,
) -> UUID:
    pbc_id = uuid4()
    session.execute(
        text(
            """
            INSERT INTO pbc_request (
                id, tenant_id, engagement_id, title, description, status,
                assigned_to_user_id, due_at
            ) VALUES (
                :i, :t, :e, :ti, :d, 'open', :a,
                CASE WHEN CAST(:due AS text) IS NULL THEN NULL
                     ELSE CAST(:due AS date) END
            )
            """
        ),
        {
            "i": str(pbc_id),
            "t": str(tenant_id),
            "e": str(req.engagement_id),
            "ti": req.title,
            "d": req.description,
            "a": str(req.assigned_preparer_id) if req.assigned_preparer_id else None,
            "due": req.due_at,
        },
    )
    emit_audit_event(
        session,
        action="pbc.created",
        tenant_id=tenant_id,
        resource_type="pbc_request",
        resource_id=pbc_id,
        actor_user_id=actor_user_id,
        payload={"title": req.title},
    )
    return pbc_id


def transition_pbc_request(
    session: Session,
    *,
    tenant_id: UUID,
    actor_user_id: UUID | None,
    pbc_id: UUID,
    to: PBCStatus,
    note: str | None = None,
) -> None:
    row = session.execute(
        text("SELECT status FROM pbc_request WHERE id = :i"),
        {"i": str(pbc_id)},
    ).mappings().first()
    if row is None:
        raise KeyError(f"pbc_request {pbc_id} not found")
    current = PBCStatus(row["status"])
    if not can_transition(current, to):
        raise InvalidPBCTransition(
            f"pbc_request {pbc_id}: {current.value} → {to.value} not allowed"
        )
    session.execute(
        text("UPDATE pbc_request SET status = :s WHERE id = :i"),
        {"s": to.value, "i": str(pbc_id)},
    )
    emit_audit_event(
        session,
        action=f"pbc.{to.value}",
        tenant_id=tenant_id,
        resource_type="pbc_request",
        resource_id=pbc_id,
        actor_user_id=actor_user_id,
        payload={"from": current.value, "to": to.value, "note": note},
    )


def auto_match_document(
    session: Session,
    *,
    tenant_id: UUID,
    engagement_id: UUID,
    document_id: UUID,
    hint_title: str | None = None,
) -> UUID | None:
    """Match a just-uploaded Document against outstanding PBC items.

    Matching is string-prefix on title today — real implementation uses
    Source_Detector category + filename heuristics. Returns the matched
    pbc_request id or None.
    """
    if not hint_title:
        return None
    row = session.execute(
        text(
            """
            SELECT id FROM pbc_request
            WHERE engagement_id = :e
              AND status IN ('open', 'sent', 'in_progress')
              AND (lower(title) = lower(:t)
                   OR lower(:t) LIKE '%' || lower(title) || '%')
            ORDER BY created_at ASC
            LIMIT 1
            """
        ),
        {"e": str(engagement_id), "t": hint_title},
    ).first()
    if row is None:
        return None
    pbc_id = UUID(str(row[0]))
    session.execute(
        text("UPDATE document SET pbc_request_id = :p WHERE id = :d"),
        {"p": str(pbc_id), "d": str(document_id)},
    )
    transition_pbc_request(
        session, tenant_id=tenant_id, actor_user_id=None,
        pbc_id=pbc_id, to=PBCStatus.RECEIVED,
        note=f"auto-matched to document {document_id}",
    )
    return pbc_id
