"""Field-validation gate (R29.3 / parent R4.24).

Every OCR'd field with confidence < threshold is gated: the Preparer
must confirm (or correct) the value before downstream steps can
post. Without this gate a low-confidence OCR read would silently
propagate into the WTB + exports, which is precisely the failure
mode tax preparation cannot tolerate.

### Threshold semantics

- Self-hosted OCR (Tesseract + DocTR): 0.98 (R29.3).
- External OCR (Textract, Azure DI): 0.95 (parent R4.24).

Firms can tune the threshold downward to 0.90 floor per R29.3 but
no lower. The gate refuses to instantiate with a threshold below
that floor.

### Persistence

Gate events live in the ``gate_event`` table (migration 0005). One
row per (run, field); resolution appends ``resolved_at`` +
``resolved_by`` + the confirmed/corrected value. The gate refuses
to consider a run complete until every event has a non-null
resolution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from accounting_parser.ocr.adapter import ExtractedField

_MIN_THRESHOLD_FLOOR = 0.90  # R29.3


class GateResolution(str, Enum):
    """How a Preparer resolved a gated field."""

    CONFIRMED = "confirmed"  # OCR value accepted as-is
    CORRECTED = "corrected"  # OCR value replaced with Preparer's input
    REJECTED = "rejected"  # Field could not be resolved; downstream refuses


@dataclass
class GateEvent:
    """One gate decision — either pending or resolved."""

    id: UUID
    tenant_id: UUID
    document_id: UUID
    page_number: int
    field_label: str
    ocr_value: str
    ocr_confidence: float
    bounding_box: dict[str, int]
    raw_confidence: dict[str, float]
    created_at: datetime
    resolved_at: datetime | None = None
    resolved_by_user_id: UUID | None = None
    resolution: GateResolution | None = None
    corrected_value: str | None = None

    @property
    def is_resolved(self) -> bool:
        return self.resolution is not None


class FieldValidationGate:
    """Computes and persists gate events for a set of OCR fields.

    Stateless — callers pass in OCR output + threshold; the gate
    returns the events to persist. Persistence is the route layer's
    responsibility (service pattern matches the rest of the codebase).
    """

    def __init__(self, *, threshold: float = 0.98) -> None:
        if threshold < _MIN_THRESHOLD_FLOOR:
            raise ValueError(
                f"threshold {threshold} below floor {_MIN_THRESHOLD_FLOOR}; "
                "R29.3 forbids setting it lower"
            )
        if threshold > 1.0:
            raise ValueError(f"threshold {threshold} > 1.0 is nonsensical")
        self.threshold = threshold

    def events_for_fields(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        page_number: int,
        fields: tuple[ExtractedField, ...],
        now: datetime,
    ) -> list[GateEvent]:
        """Return one GateEvent per field with confidence below threshold.

        High-confidence fields don't produce events — they post
        directly. Order matches input order so the UI can render in
        the same sequence the OCR reported.
        """
        return [
            GateEvent(
                id=uuid4(),
                tenant_id=tenant_id,
                document_id=document_id,
                page_number=page_number,
                field_label=f.label,
                ocr_value=f.value,
                ocr_confidence=f.confidence,
                bounding_box={
                    "x": f.bounding_box.x,
                    "y": f.bounding_box.y,
                    "width": f.bounding_box.width,
                    "height": f.bounding_box.height,
                },
                raw_confidence=dict(f.raw_confidence),
                created_at=now,
            )
            for f in fields
            if f.confidence < self.threshold
        ]

    def all_resolved(self, events: list[GateEvent]) -> bool:
        """True if every gate event has a resolution.

        Callers use this as the go/no-go for advancing the workflow
        past the OCR step. Unresolved events block posting.
        """
        return all(e.is_resolved for e in events)
