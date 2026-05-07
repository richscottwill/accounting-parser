"""Field-validation gate — Requirement 4.24 / Correctness Property 26.

Any OCR-derived Tax_Form_Field whose confidence is below 0.95 must be
Preparer-confirmed before the value can be posted to the Working_Trial_
Balance or included in a Target_System_Export.

This module owns:
- ``evaluate(result)`` → separates below-threshold from auto-post fields.
- ``confirm_field(session, field_id, corrected_value=None)`` → records a
  Preparer confirmation event in the audit log (original OCR value,
  optional corrected value, actor, timestamp).
- Blocks that the gate has been cleared are checked via
  ``all_flagged_fields_confirmed(session, parse_result_id)``.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from accounting_parser.auth.audit import emit_audit_event
from accounting_parser.ocr.adapter import ExtractedField, OCRResult

CONFIDENCE_FLOOR = 0.95


@dataclass
class GateVerdict:
    """Separation of an OCRResult's fields into auto-post vs flagged."""

    auto_post: list[ExtractedField]
    flagged: list[ExtractedField]


def evaluate(result: OCRResult, *, floor: float = CONFIDENCE_FLOOR) -> GateVerdict:
    """Split fields by confidence threshold. Pure; no DB."""
    auto, flagged = [], []
    for f in result.fields:
        (auto if f.confidence >= floor else flagged).append(f)
    return GateVerdict(auto_post=auto, flagged=flagged)


def confirm_field(
    session: Session,
    *,
    tenant_id: UUID,
    actor_user_id: UUID,
    document_id: UUID,
    field_name: str,
    original_value: str,
    original_confidence: float,
    corrected_value: str | None = None,
) -> None:
    """Record a Preparer confirm/correct event.

    The audit_log_entry is the durable record — the gate enforcement in
    higher layers (WTB posting, export emission) checks for it before
    letting a sub-0.95 value propagate.
    """
    emit_audit_event(
        session,
        action=(
            "ocr.field_corrected"
            if corrected_value is not None and corrected_value != original_value
            else "ocr.field_confirmed"
        ),
        tenant_id=tenant_id,
        resource_type="document",
        resource_id=document_id,
        actor_user_id=actor_user_id,
        payload={
            "field_name": field_name,
            "original_value": original_value,
            "original_confidence": original_confidence,
            "corrected_value": corrected_value,
        },
    )


def all_flagged_fields_confirmed(
    session: Session, *, document_id: UUID, flagged_field_names: list[str]
) -> bool:
    """Has every flagged field on ``document_id`` been confirmed?"""
    if not flagged_field_names:
        return True
    rows = session.execute(
        text(
            """
            SELECT DISTINCT payload->>'field_name' AS f
            FROM audit_log_entry
            WHERE resource_id = :d
              AND action IN ('ocr.field_confirmed','ocr.field_corrected')
            """
        ),
        {"d": str(document_id)},
    ).mappings().all()
    confirmed = {r["f"] for r in rows if r["f"]}
    return all(n in confirmed for n in flagged_field_names)
