"""Rollforward property test — Correctness Property 16.

For every pair (closed Engagement, rollforward Engagement), assert
``current.beginning_balance == prior.ending_balance`` for every Account.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import hypothesis.strategies as st
from hypothesis import HealthCheck, given, settings

from accounting_parser.model.canonical import (
    Account,
    WorkingTrialBalance,
    WTBRow,
)
from accounting_parser.rollforward import Carryforwards, rollforward


@st.composite
def closed_wtb(draw):
    n = draw(st.integers(min_value=1, max_value=8))
    rows = []
    for i in range(n):
        tax = draw(st.decimals(
            min_value=Decimal("-10000"), max_value=Decimal("10000"), places=2
        ))
        rows.append(WTBRow(
            account=Account(account_number=f"{1000+i}", account_name=f"A{i}"),
            unadjusted=tax,
            adjusted=tax,
            final=tax,
            tax_basis=tax,
        ))
    return WorkingTrialBalance(engagement_id=uuid4(), rows=tuple(rows))


@given(closed_wtb())
@settings(max_examples=50, deadline=None,
          suppress_health_check=[HealthCheck.filter_too_much])
def test_current_beginning_equals_prior_ending(wtb: WorkingTrialBalance) -> None:
    """Correctness Property 16."""
    result = rollforward(
        wtb, prior_fixed_assets=(), prior_carryforwards=Carryforwards(),
        new_engagement_id=uuid4(),
    )
    prior_by_acct = {r.account.account_number: r.tax_basis for r in wtb.rows}
    for new_row in result.new_wtb.rows:
        prior_ending = prior_by_acct[new_row.account.account_number]
        assert new_row.unadjusted == prior_ending, (
            f"rollforward broke for {new_row.account.account_number}: "
            f"prior ending {prior_ending}, new beginning {new_row.unadjusted}"
        )


def test_carryforwards_passed_through() -> None:
    cf = Carryforwards(nol=Decimal("12345.67"), amt_credit=Decimal("999.99"))
    wtb = WorkingTrialBalance(engagement_id=uuid4(), rows=())
    result = rollforward(wtb, prior_fixed_assets=(), prior_carryforwards=cf,
                         new_engagement_id=uuid4())
    assert result.new_carryforwards == cf
