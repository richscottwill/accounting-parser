"""SmokeTestAdapter scaffolding — Target format drift detection (Task 20, R24).

Each ``TargetSystemAdapter`` registers a canonical reference Engagement +
a known-good output fixture. The smoke-test runner invokes the adapter's
``emit`` against the reference and byte-compares to the fixture, modulo an
acceptable-variance allowlist (for timestamps, UUIDs, etc.).

Adapter status transitions:
    active -> at_risk (smoke test fails)
    at_risk -> blocked (48 hours after first failure)
    blocked -> active (smoke test passes again)

Celery-beat scheduling of these runs is part of the workflow-engine task
(Task 17); this module provides the pure check function.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class AdapterStatus(str, Enum):
    ACTIVE = "active"
    AT_RISK = "at_risk"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class SmokeTestResult:
    target_system: str
    passed: bool
    drift_details: str | None


def _strip_variance(text: str, variance_patterns: tuple[str, ...]) -> str:
    for pattern in variance_patterns:
        text = re.sub(pattern, "__VARIANCE__", text)
    return text


def check_output_matches_fixture(
    *,
    target_system: str,
    actual_path: Path,
    fixture_path: Path,
    variance_patterns: tuple[str, ...] = (
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}",  # iso timestamps
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",  # UUIDs
    ),
) -> SmokeTestResult:
    """Byte-compare two text outputs after masking an acceptable variance
    allowlist. Binary outputs (ZIP, XLSX) are unsupported at MVP — those
    get byte-identical comparison or a deferred check."""
    actual = actual_path.read_text(encoding="utf-8", errors="replace")
    expected = fixture_path.read_text(encoding="utf-8", errors="replace")
    actual_masked = _strip_variance(actual, variance_patterns)
    expected_masked = _strip_variance(expected, variance_patterns)
    if actual_masked == expected_masked:
        return SmokeTestResult(
            target_system=target_system, passed=True, drift_details=None,
        )
    # Find first divergence position
    diff_at = 0
    for i, (a, e) in enumerate(zip(actual_masked, expected_masked)):
        if a != e:
            diff_at = i
            break
    window = 80
    a_slice = actual_masked[max(0, diff_at - window): diff_at + window]
    e_slice = expected_masked[max(0, diff_at - window): diff_at + window]
    details = (
        f"first divergence at offset {diff_at}:\n"
        f"  expected (masked): {e_slice!r}\n"
        f"  actual   (masked): {a_slice!r}"
    )
    return SmokeTestResult(
        target_system=target_system, passed=False, drift_details=details,
    )


def transition_status(
    current: AdapterStatus,
    smoke_test_passed: bool,
    hours_since_first_failure: int,
) -> AdapterStatus:
    """Apply the active/at_risk/blocked transition rules.

    Per design Section 3.9 and R24.8:
    - pass & any state -> active
    - fail & active -> at_risk
    - fail & at_risk & >=48h elapsed -> blocked
    - fail & at_risk & <48h -> at_risk (grace window)
    - fail & blocked -> blocked (stays)
    """
    if smoke_test_passed:
        return AdapterStatus.ACTIVE
    if current == AdapterStatus.ACTIVE:
        return AdapterStatus.AT_RISK
    if current == AdapterStatus.AT_RISK:
        if hours_since_first_failure >= 48:
            return AdapterStatus.BLOCKED
        return AdapterStatus.AT_RISK
    return AdapterStatus.BLOCKED
