"""FieldValidationGate tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from accounting_parser.ocr.adapter import BoundingBox, ExtractedField
from accounting_parser.ocr.gate import FieldValidationGate, GateResolution


def _field(label: str, conf: float) -> ExtractedField:
    return ExtractedField(
        label=label,
        value=f"{label}_value",
        confidence=conf,
        bounding_box=BoundingBox(0, 0, 10, 10),
        raw_confidence={"doctr_box": conf, "tesseract_char": conf},
    )


def test_threshold_floor_enforced():
    """R29.3: setting below 0.90 raises."""
    with pytest.raises(ValueError, match="floor"):
        FieldValidationGate(threshold=0.80)


def test_threshold_above_one_rejected():
    with pytest.raises(ValueError, match="> 1.0"):
        FieldValidationGate(threshold=1.5)


def test_default_threshold_is_self_hosted_098():
    """Default matches R29.3 (self-hosted OCR threshold)."""
    g = FieldValidationGate()
    assert g.threshold == 0.98


def test_high_confidence_fields_do_not_gate():
    """Fields >= threshold produce zero events."""
    gate = FieldValidationGate(threshold=0.98)
    fields = (_field("box1", 0.99), _field("box2", 0.985))
    events = gate.events_for_fields(
        tenant_id=uuid4(),
        document_id=uuid4(),
        page_number=1,
        fields=fields,
        now=datetime.now(UTC),
    )
    assert events == []


def test_low_confidence_fields_gate():
    """Fields below threshold produce events with raw confidences preserved."""
    gate = FieldValidationGate(threshold=0.98)
    fields = (_field("wages", 0.75), _field("tips", 0.92))
    events = gate.events_for_fields(
        tenant_id=uuid4(),
        document_id=uuid4(),
        page_number=1,
        fields=fields,
        now=datetime.now(UTC),
    )
    assert len(events) == 2
    assert {e.field_label for e in events} == {"wages", "tips"}
    assert all(e.raw_confidence["doctr_box"] <= 0.95 for e in events)


def test_event_ordering_matches_input():
    """Gate preserves the OCR-reported order of fields for the UI."""
    gate = FieldValidationGate(threshold=0.98)
    fields = (
        _field("field_a", 0.5),
        _field("field_b", 0.6),
        _field("field_c", 0.7),
    )
    events = gate.events_for_fields(
        tenant_id=uuid4(),
        document_id=uuid4(),
        page_number=1,
        fields=fields,
        now=datetime.now(UTC),
    )
    assert [e.field_label for e in events] == ["field_a", "field_b", "field_c"]


def test_all_resolved_false_with_pending_event():
    gate = FieldValidationGate(threshold=0.98)
    events = gate.events_for_fields(
        tenant_id=uuid4(),
        document_id=uuid4(),
        page_number=1,
        fields=(_field("x", 0.5),),
        now=datetime.now(UTC),
    )
    assert gate.all_resolved(events) is False


def test_all_resolved_true_after_confirming():
    gate = FieldValidationGate(threshold=0.98)
    events = gate.events_for_fields(
        tenant_id=uuid4(),
        document_id=uuid4(),
        page_number=1,
        fields=(_field("x", 0.5), _field("y", 0.6)),
        now=datetime.now(UTC),
    )
    for e in events:
        e.resolved_at = datetime.now(UTC)
        e.resolved_by_user_id = uuid4()
        e.resolution = GateResolution.CONFIRMED
    assert gate.all_resolved(events) is True


def test_external_ocr_uses_lower_threshold():
    """Parent R4.24 threshold is 0.95; external providers opt in via that."""
    gate = FieldValidationGate(threshold=0.95)
    # 0.96 passes 0.95 but would be gated under 0.98.
    events = gate.events_for_fields(
        tenant_id=uuid4(),
        document_id=uuid4(),
        page_number=1,
        fields=(_field("wages", 0.96),),
        now=datetime.now(UTC),
    )
    assert events == []
