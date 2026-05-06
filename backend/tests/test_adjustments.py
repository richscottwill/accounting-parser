"""Adjustment engine tests — Correctness Property 1 (parse-and-proposal determinism).

Running the same templates twice against the same WTB produces byte-identical
proposed entries.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from accounting_parser.adjustments import (
    STARTER_LIBRARY_2025,
    run_book_to_tax,
)
from accounting_parser.model.canonical import (
    Account,
    WorkingTrialBalance,
    WTBRow,
)
from accounting_parser.model.pretty_printer import canonical_json


def _fixture_wtb() -> WorkingTrialBalance:
    rows = (
        WTBRow(
            account=Account(account_number="6200", account_name="Meals & Entertainment"),
            unadjusted=Decimal("2000.00"),
            adjusted=Decimal("2000.00"),
            final=Decimal("2000.00"),
            tax_basis=Decimal("2000.00"),
        ),
        WTBRow(
            account=Account(account_number="6201", account_name="Meals - Travel"),
            unadjusted=Decimal("1000.00"),
            adjusted=Decimal("1000.00"),
            final=Decimal("1000.00"),
            tax_basis=Decimal("1000.00"),
        ),
        WTBRow(
            account=Account(account_number="6210", account_name="Entertainment"),
            unadjusted=Decimal("500.00"),
            adjusted=Decimal("500.00"),
            final=Decimal("500.00"),
            tax_basis=Decimal("500.00"),
        ),
        WTBRow(
            account=Account(account_number="6900", account_name="Fines and Penalties"),
            unadjusted=Decimal("250.00"),
            adjusted=Decimal("250.00"),
            final=Decimal("250.00"),
            tax_basis=Decimal("250.00"),
        ),
        WTBRow(
            account=Account(account_number="4100", account_name="Tax-Exempt Interest Income"),
            unadjusted=Decimal("120.00"),
            adjusted=Decimal("120.00"),
            final=Decimal("120.00"),
            tax_basis=Decimal("120.00"),
        ),
    )
    return WorkingTrialBalance(engagement_id=uuid4(), rows=rows)


def test_meals_50_percent_addback() -> None:
    wtb = _fixture_wtb()
    proposed = run_book_to_tax(wtb, STARTER_LIBRARY_2025, tax_year=2025)
    # Meals (2000) -> 1000 addback. Meals-Travel (1000) -> 500 addback.
    meals_entries = [p for p in proposed if p.template_id == "meals_50_percent_limit"]
    assert len(meals_entries) == 2
    addbacks = sorted(sum(leg.debit for leg in e.legs) for e in meals_entries)
    assert addbacks == [Decimal("500.00"), Decimal("1000.00")]


def test_entertainment_disallowance() -> None:
    wtb = _fixture_wtb()
    proposed = run_book_to_tax(wtb, STARTER_LIBRARY_2025, tax_year=2025)
    ent_entries = [p for p in proposed if p.template_id == "entertainment_disallowance"]
    assert len(ent_entries) == 1
    assert sum(leg.debit for leg in ent_entries[0].legs) == Decimal("500.00")


def test_deterministic_proposals_correctness_property_1() -> None:
    """Correctness Property 1: running templates twice against the same
    WTB produces byte-identical proposed entries."""
    wtb = _fixture_wtb()
    first = run_book_to_tax(wtb, STARTER_LIBRARY_2025, tax_year=2025)
    second = run_book_to_tax(wtb, STARTER_LIBRARY_2025, tax_year=2025)
    # Strip nothing: entry_ids must match (UUIDv5 from stable inputs).
    a_json = [canonical_json(e) for e in first]
    b_json = [canonical_json(e) for e in second]
    assert a_json == b_json, (
        "Run-to-run drift in proposed entries — Correctness Property 1 violated"
    )


def test_proposals_are_sorted() -> None:
    wtb = _fixture_wtb()
    proposed = run_book_to_tax(wtb, STARTER_LIBRARY_2025, tax_year=2025)
    keys = [(e.template_id, e.legs[0].account.account_number) for e in proposed]
    assert keys == sorted(keys)
