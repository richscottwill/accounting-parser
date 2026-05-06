"""Metering tests — Correctness Property 28 (monotonic counters).

100 arbitrary event sequences; for every one, assert sum_increments is
non-decreasing regardless of event ordering.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import hypothesis.strategies as st
import pytest
from hypothesis import HealthCheck, given, settings

from accounting_parser.metering import (
    CorrectionEvent,
    IncrementEvent,
    MonotonicityViolation,
    compute_counters,
)


METRICS = [
    "documents_ingested",
    "documents_rejected",
    "ocr_pages",
    "textract_pages",
    "azure_di_pages",
    "exports_cch",
    "exports_ultratax",
    "failed_exports_cch",
    "workflow_runs_started",
    "workflow_runs_completed",
]


@st.composite
def event_sequence(draw):
    # Generate a sequence of 1-20 events, all for the same engagement
    engagement_id = draw(st.uuids())
    n = draw(st.integers(min_value=1, max_value=20))
    events = []
    for _ in range(n):
        metric = draw(st.sampled_from(METRICS))
        if draw(st.booleans()):
            events.append(IncrementEvent(
                engagement_id=engagement_id,
                metric=metric,
                amount=draw(st.decimals(min_value=Decimal("0"), max_value=Decimal("100"), places=2)),
            ))
        else:
            events.append(CorrectionEvent(
                engagement_id=engagement_id,
                metric=metric,
                amount=draw(st.decimals(min_value=Decimal("-50"), max_value=Decimal("50"), places=2)),
                reason="test correction",
            ))
    return events


@given(event_sequence())
@settings(max_examples=100, deadline=None,
          suppress_health_check=[HealthCheck.filter_too_much])
def test_sum_increments_is_monotonic(events) -> None:
    """Correctness Property 28."""
    counters = compute_counters(events)
    # Simulate streaming: replay prefixes and confirm sum_increments never decreases
    prev: dict = {}
    for i in range(1, len(events) + 1):
        snap_map = compute_counters(events[:i])
        for key, snap in snap_map.items():
            prev_val = prev.get(key, Decimal("0"))
            assert snap.sum_increments >= prev_val, (
                f"sum_increments decreased: {prev_val} -> {snap.sum_increments}"
            )
            prev[key] = snap.sum_increments


def test_increment_event_rejects_negative() -> None:
    with pytest.raises(ValueError, match="must be >= 0"):
        IncrementEvent(engagement_id=uuid4(), metric="x", amount=Decimal("-1"))


def test_corrections_tracked_separately_from_increments() -> None:
    eng = uuid4()
    events = [
        IncrementEvent(engagement_id=eng, metric="ocr_pages", amount=Decimal("10")),
        IncrementEvent(engagement_id=eng, metric="ocr_pages", amount=Decimal("5")),
        CorrectionEvent(engagement_id=eng, metric="ocr_pages",
                        amount=Decimal("-3"), reason="double-counted blank pages"),
    ]
    counters = compute_counters(events)
    snap = counters[(eng, "ocr_pages")]
    assert snap.sum_increments == Decimal("15")
    assert snap.sum_corrections == Decimal("-3")
    assert snap.net == Decimal("12")
