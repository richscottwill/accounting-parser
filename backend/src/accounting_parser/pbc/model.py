"""PBC domain model + state machine.

The DB persistence layer lives in migration ``pbc_request`` which
was defined in parent Task 3's schema (so we don't need a new
migration here — the table exists, this module is the validated
Python shape around it).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


class PbcCategory(str, Enum):
    """Canonical PBC categories (R16.1)."""

    TRIAL_BALANCE = "trial_balance"
    GENERAL_LEDGER = "general_ledger"
    BANK_STATEMENT = "bank_statement"
    INVESTMENT_STATEMENT = "investment_statement"
    PAYROLL_RECORD = "payroll_record"
    FIXED_ASSET_SCHEDULE = "fixed_asset_schedule"
    ACCOUNTS_RECEIVABLE_AGING = "accounts_receivable_aging"
    ACCOUNTS_PAYABLE_AGING = "accounts_payable_aging"
    INVENTORY_COUNT = "inventory_count"
    LOAN_STATEMENT = "loan_statement"
    W2 = "w2"
    FORM_1099 = "form_1099"
    FORM_K1 = "form_k1"
    FORM_1098 = "form_1098"
    PRIOR_YEAR_RETURN = "prior_year_return"
    OTHER = "other"


CANONICAL_CATEGORIES: frozenset[PbcCategory] = frozenset(PbcCategory)


class PbcStatus(str, Enum):
    """PBC request lifecycle states."""

    NOT_REQUESTED = "not_requested"
    REQUESTED = "requested"
    RECEIVED = "received"
    UNDER_REVIEW = "under_review"
    ACCEPTED = "accepted"
    REJECTED_RESUBMIT = "rejected_resubmit"
    WAIVED = "waived"


_ALLOWED_TRANSITIONS: dict[PbcStatus, frozenset[PbcStatus]] = {
    PbcStatus.NOT_REQUESTED: frozenset({PbcStatus.REQUESTED, PbcStatus.WAIVED}),
    PbcStatus.REQUESTED: frozenset(
        {PbcStatus.RECEIVED, PbcStatus.WAIVED, PbcStatus.REJECTED_RESUBMIT}
    ),
    PbcStatus.RECEIVED: frozenset({PbcStatus.UNDER_REVIEW, PbcStatus.REJECTED_RESUBMIT}),
    PbcStatus.UNDER_REVIEW: frozenset({PbcStatus.ACCEPTED, PbcStatus.REJECTED_RESUBMIT}),
    PbcStatus.REJECTED_RESUBMIT: frozenset({PbcStatus.RECEIVED, PbcStatus.WAIVED}),
    PbcStatus.ACCEPTED: frozenset(),  # terminal
    PbcStatus.WAIVED: frozenset(),  # terminal
}


class InvalidPbcTransitionError(RuntimeError):
    """Raised on a status transition not in the state machine."""


@dataclass
class PbcRequest:
    """One PBC request for a specific document category on an engagement."""

    id: UUID
    tenant_id: UUID
    engagement_id: UUID
    client_id: UUID
    category: PbcCategory
    status: PbcStatus
    description: str
    requested_at: datetime | None = None
    received_at: datetime | None = None
    accepted_at: datetime | None = None
    document_id: UUID | None = None

    def transition_to(self, new_status: PbcStatus) -> None:
        """Validate + apply a status transition.

        Raises ``InvalidPbcTransitionError`` if the transition isn't
        allowed from the current state.
        """
        allowed = _ALLOWED_TRANSITIONS.get(self.status, frozenset())
        if new_status not in allowed:
            raise InvalidPbcTransitionError(
                f"cannot transition {self.status.value} → {new_status.value}; "
                f"allowed: {sorted(s.value for s in allowed)}"
            )
        self.status = new_status
