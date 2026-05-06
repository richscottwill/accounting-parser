"""SmokeTestAdapter tests."""

from __future__ import annotations

from pathlib import Path

from accounting_parser.exporters.smoke_test import (
    AdapterStatus,
    check_output_matches_fixture,
    transition_status,
)


def test_smoke_test_passes_with_identical_text(tmp_path: Path) -> None:
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("hello\nworld\n")
    b.write_text("hello\nworld\n")
    result = check_output_matches_fixture(
        target_system="cch", actual_path=a, fixture_path=b,
    )
    assert result.passed


def test_smoke_test_accepts_timestamp_variance(tmp_path: Path) -> None:
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("run at 2026-01-01T12:00:00Z\nvalue=42\n")
    b.write_text("run at 2025-01-01T00:00:00Z\nvalue=42\n")
    result = check_output_matches_fixture(
        target_system="x", actual_path=a, fixture_path=b,
    )
    assert result.passed


def test_smoke_test_flags_real_drift(tmp_path: Path) -> None:
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("Account Number,Amount\n1000,500.00\n")
    b.write_text("AccountNumber,Amount\n1000,500.00\n")  # missing space
    result = check_output_matches_fixture(
        target_system="cch", actual_path=a, fixture_path=b,
    )
    assert not result.passed
    assert "first divergence" in (result.drift_details or "")


def test_transition_active_to_at_risk_on_failure() -> None:
    assert transition_status(AdapterStatus.ACTIVE, False, 0) == AdapterStatus.AT_RISK


def test_transition_at_risk_to_blocked_after_grace() -> None:
    assert transition_status(AdapterStatus.AT_RISK, False, 48) == AdapterStatus.BLOCKED


def test_transition_at_risk_stays_during_grace() -> None:
    assert transition_status(AdapterStatus.AT_RISK, False, 12) == AdapterStatus.AT_RISK


def test_transition_pass_recovers_to_active() -> None:
    assert transition_status(AdapterStatus.BLOCKED, True, 100) == AdapterStatus.ACTIVE
    assert transition_status(AdapterStatus.AT_RISK, True, 2) == AdapterStatus.ACTIVE
