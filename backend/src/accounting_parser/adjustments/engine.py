"""Adjustment template Protocol + run_book_to_tax orchestrator.

Templates are deterministic pure functions from (WorkingTrialBalance,
TaxYearParameterSet) to a list of proposed JournalEntryAdjustment. No
side effects; no IO. Promotion from proposed to posted happens in a
separate user action (Preparer approval).

Correctness Property 1: running the same template set twice against the
same inputs produces byte-identical proposed entries.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID, uuid5, NAMESPACE_URL

from accounting_parser.depreciation.tax_year_parameters import (
    TaxYearParameterSet,
    get_tax_year_parameters,
)
from accounting_parser.model.canonical import (
    JournalEntryAdjustment,
    WorkingTrialBalance,
)


@dataclass(frozen=True)
class TemplateContext:
    """Read-only context passed to every template."""

    wtb: WorkingTrialBalance
    params: TaxYearParameterSet
    tax_year: int


class AdjustmentTemplate(Protocol):
    """Protocol every template must implement."""

    template_id: str
    schedule_m1_line: str | None
    schedule_m3_line: str | None

    def propose(self, ctx: TemplateContext) -> list[JournalEntryAdjustment]:
        """Return 0 or more proposed entries."""
        ...


def deterministic_entry_id(template_id: str, account_number: str, tax_year: int) -> UUID:
    """Deterministic UUIDv5 so the same inputs always produce the same entry_id
    (Correctness Property 1)."""
    return uuid5(NAMESPACE_URL, f"accounting-parser/{template_id}/{account_number}/{tax_year}")


def run_book_to_tax(
    wtb: WorkingTrialBalance,
    templates: list[AdjustmentTemplate],
    *,
    tax_year: int,
) -> list[JournalEntryAdjustment]:
    """Run every template, collect proposed entries, sort deterministically.

    Deterministic ordering per Correctness Property 1: sort by
    (template_id, primary_account_number).
    """
    params = get_tax_year_parameters(tax_year)
    ctx = TemplateContext(wtb=wtb, params=params, tax_year=tax_year)
    all_proposed: list[JournalEntryAdjustment] = []
    for template in templates:
        all_proposed.extend(template.propose(ctx))

    def sort_key(entry: JournalEntryAdjustment) -> tuple[str, str]:
        tpl_id = entry.template_id or ""
        # Primary account = first leg's account number (deterministic)
        acct = entry.legs[0].account.account_number if entry.legs else ""
        return (tpl_id, acct)

    return sorted(all_proposed, key=sort_key)
