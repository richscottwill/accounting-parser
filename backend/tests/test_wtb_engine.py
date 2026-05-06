"""WTB tie-out property test — Correctness Property 12.

For every arbitrary sequence of (unadjusted, [AJEs]), apply via the
engine, assert unadjusted + sum_aje == adjusted for every account.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import hypothesis.strategies as st
from hypothesis import HealthCheck, given, settings

from accounting_parser.model.canonical import (
    Account,
    EntryStatus,
    EntryType,
    JournalEntryAdjustment,
    JournalLeg,
    WorkingTrialBalance,
)
from accounting_parser.wtb import (
    PostEntryChange,
    SetUnadjustedChange,
    apply_change,
)


@st.composite
def wtb_setup(draw):
    """Generate a WTB with N accounts and M AJEs."""
    n_accts = draw(st.integers(min_value=1, max_value=6))
    accounts = tuple(
        Account(account_number=f"{1000+i}", account_name=f"A{i}") for i in range(n_accts)
    )
    balances = [
        draw(st.decimals(min_value=Decimal("-10000"), max_value=Decimal("10000"), places=2))
        for _ in range(n_accts)
    ]
    n_ajes = draw(st.integers(min_value=0, max_value=5))
    ajes = []
    for _ in range(n_ajes):
        # Build a two-leg balanced AJE on two random accounts.
        i_dr = draw(st.integers(min_value=0, max_value=n_accts - 1))
        i_cr = draw(st.integers(min_value=0, max_value=n_accts - 1))
        amt = draw(st.decimals(min_value=Decimal("0.01"), max_value=Decimal("5000"), places=2))
        ajes.append(JournalEntryAdjustment(
            entry_id=uuid4(),
            entry_type=EntryType.AJE,
            description="test AJE",
            legs=(
                JournalLeg(account=accounts[i_dr], debit=amt, credit=Decimal("0")),
                JournalLeg(account=accounts[i_cr], debit=Decimal("0"), credit=amt),
            ),
            status=EntryStatus.POSTED,
        ))
    return accounts, balances, ajes


@given(wtb_setup())
@settings(max_examples=1000, deadline=None,
          suppress_health_check=[HealthCheck.filter_too_much])
def test_wtb_tie_out_invariant(inputs) -> None:
    """Correctness Property 12."""
    accounts, balances, ajes = inputs
    wtb = WorkingTrialBalance(engagement_id=uuid4(), rows=())
    for acc, bal in zip(accounts, balances):
        wtb = apply_change(wtb, SetUnadjustedChange(
            account_number=acc.account_number,
            account=acc,
            unadjusted=bal,
        ))
    for aje in ajes:
        wtb = apply_change(wtb, PostEntryChange(entry=aje))
    # Tie-out invariant holds for every row (apply_change enforced it at
    # every step, but let's double-check).
    for row in wtb.rows:
        assert row.unadjusted + row.sum_aje == row.adjusted
        assert row.adjusted + row.sum_rje == row.final
        assert row.final + row.sum_tje == row.tax_basis
