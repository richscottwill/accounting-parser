"""Event-sourced metering counters."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Union
from uuid import UUID


@dataclass(frozen=True)
class IncrementEvent:
    """A normal monotonic increment. Value must be non-negative."""

    engagement_id: UUID
    metric: str
    amount: Decimal

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError("IncrementEvent.amount must be >= 0; "
                             "use CorrectionEvent for adjustments")


@dataclass(frozen=True)
class CorrectionEvent:
    """An explicit negative adjustment that the system allows but audits.

    Every correction carries a reason. The counter's raw sum_increments
    is still monotonic; the correction_total is tracked separately.
    """

    engagement_id: UUID
    metric: str
    amount: Decimal  # negative or positive
    reason: str


MeteringEvent = Union[IncrementEvent, CorrectionEvent]


class MonotonicityViolation(Exception):
    """Raised if a non-correction event would decrease a counter."""


@dataclass(frozen=True)
class CounterSnapshot:
    """Immutable view of a counter's state."""

    sum_increments: Decimal = Decimal("0")
    sum_corrections: Decimal = Decimal("0")

    @property
    def net(self) -> Decimal:
        return self.sum_increments + self.sum_corrections


def replay(events: list[MeteringEvent]) -> dict[tuple[UUID, str], CounterSnapshot]:
    """Fold a sequence of events into per-(engagement, metric) counters.

    Enforces the monotonicity invariant: ``sum_increments`` is non-decreasing
    across any subsequence. Any ``IncrementEvent`` with ``amount < 0`` raises
    ``MonotonicityViolation``.
    """
    counters: dict[tuple[UUID, str], CounterSnapshot] = {}
    prev_sum_increments: dict[tuple[UUID, str], Decimal] = {}
    for ev in events:
        key = (ev.engagement_id, ev.metric)
        snap = counters.get(key, CounterSnapshot())
        if isinstance(ev, IncrementEvent):
            # Monotonicity: sum_increments can only go up.
            new_sum = snap.sum_increments + ev.amount
            prev = prev_sum_increments.get(key, Decimal("0"))
            if new_sum < prev:
                # Cannot happen given __post_init__ rejects negative, but
                # explicit for future safety.
                raise MonotonicityViolation(
                    f"Counter {key} non-monotonic: {prev} -> {new_sum}"
                )
            prev_sum_increments[key] = new_sum
            counters[key] = CounterSnapshot(
                sum_increments=new_sum,
                sum_corrections=snap.sum_corrections,
            )
        else:
            counters[key] = CounterSnapshot(
                sum_increments=snap.sum_increments,
                sum_corrections=snap.sum_corrections + ev.amount,
            )
    return counters


def compute_counters(
    events: list[MeteringEvent]
) -> dict[tuple[UUID, str], CounterSnapshot]:
    """Alias for ``replay`` with a more domain-friendly name."""
    return replay(events)
