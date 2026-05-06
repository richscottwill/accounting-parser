"""Engagement metering: monotonic event-sourced counters.

Per R24.5-R24.7: counter per Engagement-and-metric is monotonically
increasing when events are ``increment``. Corrections are modeled as
negative-adjustment events, preserving the audit trail without rewriting
history (parallels the hash-chain audit log invariant).

Correctness Property 28: given any sequence of arbitrary events, the
monotonicity invariant holds — every counter's sequence-ordered
partial sum is non-decreasing across increment events, and decreases
only via explicit correction events.
"""

from accounting_parser.metering.counter import (
    CorrectionEvent,
    IncrementEvent,
    MeteringEvent,
    MonotonicityViolation,
    compute_counters,
    replay,
)

__all__ = [
    "MeteringEvent",
    "IncrementEvent",
    "CorrectionEvent",
    "compute_counters",
    "replay",
    "MonotonicityViolation",
]
