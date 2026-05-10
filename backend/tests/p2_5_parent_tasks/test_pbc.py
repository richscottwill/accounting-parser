"""Parent Task 23 PBC domain model + lifecycle."""

from __future__ import annotations

from uuid import uuid4

import pytest

from accounting_parser.pbc import (
    CANONICAL_CATEGORIES,
    InvalidPbcTransitionError,
    PbcCategory,
    PbcRequest,
    PbcStatus,
)


def _pbc(status: PbcStatus = PbcStatus.NOT_REQUESTED) -> PbcRequest:
    return PbcRequest(
        id=uuid4(),
        tenant_id=uuid4(),
        engagement_id=uuid4(),
        client_id=uuid4(),
        category=PbcCategory.TRIAL_BALANCE,
        status=status,
        description="Client TB for Q4",
    )


def test_canonical_categories_include_tax_forms():
    """Task 23 R16.1: W-2, 1099, K-1, 1098 all canonicalized."""
    labels = {c.value for c in CANONICAL_CATEGORIES}
    assert {"w2", "form_1099", "form_k1", "form_1098"}.issubset(labels)


def test_happy_path_transition_sequence():
    pbc = _pbc()
    pbc.transition_to(PbcStatus.REQUESTED)
    pbc.transition_to(PbcStatus.RECEIVED)
    pbc.transition_to(PbcStatus.UNDER_REVIEW)
    pbc.transition_to(PbcStatus.ACCEPTED)
    assert pbc.status is PbcStatus.ACCEPTED


def test_reject_and_resubmit_cycle():
    pbc = _pbc(PbcStatus.UNDER_REVIEW)
    pbc.transition_to(PbcStatus.REJECTED_RESUBMIT)
    pbc.transition_to(PbcStatus.RECEIVED)
    pbc.transition_to(PbcStatus.UNDER_REVIEW)
    pbc.transition_to(PbcStatus.ACCEPTED)
    assert pbc.status is PbcStatus.ACCEPTED


def test_waive_from_not_requested():
    pbc = _pbc()
    pbc.transition_to(PbcStatus.WAIVED)
    assert pbc.status is PbcStatus.WAIVED


def test_cannot_skip_requested_to_accepted():
    pbc = _pbc()
    with pytest.raises(InvalidPbcTransitionError):
        pbc.transition_to(PbcStatus.ACCEPTED)


def test_cannot_transition_from_terminal_state():
    pbc = _pbc(PbcStatus.ACCEPTED)
    with pytest.raises(InvalidPbcTransitionError):
        pbc.transition_to(PbcStatus.REQUESTED)


def test_error_message_includes_allowed_transitions():
    pbc = _pbc(PbcStatus.REQUESTED)
    with pytest.raises(InvalidPbcTransitionError) as exc:
        pbc.transition_to(PbcStatus.ACCEPTED)
    assert "received" in str(exc.value).lower()
