"""Rollforward: prior-year ending state -> current-year beginning state.

R19.1-R19.5: carry forward account balances, fixed assets (beginning
accumulated = prior ending), and carryforward items (NOL, Section 179
carryover, capital loss, charitable, QBI, passive activity, at-risk,
AMT credit).

Identity match on ``(tenant_id, client_id, account_number)`` preserves
existing classifications and overrides automatically (the identity itself
is the continuity — the model side has no hidden state).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from accounting_parser.model.canonical import (
    FixedAsset,
    WorkingTrialBalance,
    WTBRow,
)


@dataclass(frozen=True)
class Carryforwards:
    """Tax-attribute carryforwards flowing year-over-year."""

    nol: Decimal = Decimal("0")
    section_179_carryover: Decimal = Decimal("0")
    capital_loss: Decimal = Decimal("0")
    charitable: Decimal = Decimal("0")
    qbi_loss: Decimal = Decimal("0")
    passive_activity: Decimal = Decimal("0")
    at_risk: Decimal = Decimal("0")
    amt_credit: Decimal = Decimal("0")


@dataclass(frozen=True)
class RollforwardResult:
    new_wtb: WorkingTrialBalance
    new_fixed_assets: tuple[FixedAsset, ...]
    new_carryforwards: Carryforwards


def _carry_balance(row: WTBRow) -> Decimal:
    """Prior ending balance = prior tax_basis (or final if not tax-adjusted)."""
    return row.tax_basis if row.tax_basis != 0 else row.final


def rollforward(
    prior_wtb: WorkingTrialBalance,
    prior_fixed_assets: tuple[FixedAsset, ...],
    prior_carryforwards: Carryforwards,
    *,
    new_engagement_id,
) -> RollforwardResult:
    """Roll a closed Engagement forward into a new one (R19.1-R19.5).

    Correctness Property 16: for every account,
    ``current.beginning_balance == prior.ending_balance``.
    """
    new_rows = tuple(
        WTBRow(
            account=row.account,
            prior_year=_carry_balance(row),
            unadjusted=_carry_balance(row),  # begins as prior ending
        )
        for row in prior_wtb.rows
    )
    new_wtb = WorkingTrialBalance(engagement_id=new_engagement_id, rows=new_rows)

    # Fixed assets roll forward: prior ending accumulated -> current-year
    # beginning accumulated. At MVP we don't yet track accumulated dep on
    # the FixedAsset model (it's derived at compute time), so the assets
    # themselves pass through unchanged and the depreciation engine
    # resumes from where it left off.
    return RollforwardResult(
        new_wtb=new_wtb,
        new_fixed_assets=prior_fixed_assets,
        new_carryforwards=prior_carryforwards,
    )
