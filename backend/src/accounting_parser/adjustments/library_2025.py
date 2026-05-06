"""Starter Adjustment_Library templates for Tax_Year 2025.

Each template:
- Has a stable ``template_id`` used in deterministic entry-id derivation.
- Maps to a specific Schedule M-1 / M-3 line where applicable.
- Produces zero or more proposed JournalEntryAdjustment records.

Templates deliberately keep logic simple at MVP — real tax rules are more
nuanced. Each carries a docstring with the simplifying assumption.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from accounting_parser.adjustments.engine import (
    TemplateContext,
    deterministic_entry_id,
)
from accounting_parser.model.canonical import (
    Account,
    EntryStatus,
    EntryType,
    JournalEntryAdjustment,
    JournalLeg,
)


# Shared addback-side / tax-expense-side accounts used by the starter templates.
M1_ADDBACK_ACCOUNT = Account(
    account_number="9900",
    account_name="Schedule M-1 Book/Tax Differences Suspense",
)


def _find_rows_by_name_contains(ctx: TemplateContext, *needles: str):
    """Case-insensitive account-name substring search across WTB rows."""
    out = []
    for row in ctx.wtb.rows:
        name_lower = row.account.account_name.lower()
        if any(n.lower() in name_lower for n in needles):
            out.append(row)
    return out


@dataclass(frozen=True)
class _TemplateBase:
    template_id: str
    schedule_m1_line: str | None
    schedule_m3_line: str | None


class MealsFiftyPercentLimit(_TemplateBase):
    """50% Meals limit per IRC §274(n)(1).

    Simplification: looks for any account with 'meals' in the name, posts a
    50% addback of the unadjusted balance. Does not distinguish travel vs
    in-office vs client-facing meals.
    """

    def __init__(self) -> None:
        super().__init__(
            template_id="meals_50_percent_limit",
            schedule_m1_line="M-1 Line 5 (disallowed meals)",
            schedule_m3_line="M-3 Part III Line 8",
        )

    def propose(self, ctx: TemplateContext) -> list[JournalEntryAdjustment]:
        out = []
        for row in _find_rows_by_name_contains(ctx, "meals"):
            addback = (row.unadjusted * Decimal("0.50")).quantize(Decimal("0.01"))
            if addback == 0:
                continue
            out.append(JournalEntryAdjustment(
                entry_id=deterministic_entry_id(
                    self.template_id, row.account.account_number, ctx.tax_year
                ),
                entry_type=EntryType.TJE,
                description=f"50% meals limit addback per IRC §274(n) — {row.account.account_name}",
                legs=(
                    JournalLeg(
                        account=M1_ADDBACK_ACCOUNT,
                        debit=addback,
                        credit=Decimal("0"),
                    ),
                    JournalLeg(
                        account=row.account,
                        debit=Decimal("0"),
                        credit=addback,
                    ),
                ),
                status=EntryStatus.PROPOSED,
                template_id=self.template_id,
            ))
        return out


class EntertainmentDisallowance(_TemplateBase):
    """100% entertainment disallowance per IRC §274(a)(1) (TCJA)."""

    def __init__(self) -> None:
        super().__init__(
            template_id="entertainment_disallowance",
            schedule_m1_line="M-1 Line 5",
            schedule_m3_line="M-3 Part III Line 8",
        )

    def propose(self, ctx: TemplateContext) -> list[JournalEntryAdjustment]:
        out = []
        for row in _find_rows_by_name_contains(ctx, "entertainment"):
            # Skip combined "Meals & Entertainment" accounts — those are
            # handled at 50% by MealsFiftyPercentLimit. A dedicated
            # entertainment-only account gets the 100% disallowance.
            if "meals" in row.account.account_name.lower():
                continue
            amt = row.unadjusted
            if amt == 0:
                continue
            out.append(JournalEntryAdjustment(
                entry_id=deterministic_entry_id(
                    self.template_id, row.account.account_number, ctx.tax_year
                ),
                entry_type=EntryType.TJE,
                description=f"100% entertainment disallowance per IRC §274(a)(1) — {row.account.account_name}",
                legs=(
                    JournalLeg(account=M1_ADDBACK_ACCOUNT, debit=amt, credit=Decimal("0")),
                    JournalLeg(account=row.account, debit=Decimal("0"), credit=amt),
                ),
                status=EntryStatus.PROPOSED,
                template_id=self.template_id,
            ))
        return out


class FinesAndPenaltiesAddback(_TemplateBase):
    """IRC §162(f): fines and penalties paid to a government are not deductible."""

    def __init__(self) -> None:
        super().__init__(
            template_id="fines_and_penalties_addback",
            schedule_m1_line="M-1 Line 5",
            schedule_m3_line="M-3 Part III Line 11",
        )

    def propose(self, ctx: TemplateContext) -> list[JournalEntryAdjustment]:
        out = []
        for row in _find_rows_by_name_contains(ctx, "fine", "penalt"):
            amt = row.unadjusted
            if amt == 0:
                continue
            out.append(JournalEntryAdjustment(
                entry_id=deterministic_entry_id(
                    self.template_id, row.account.account_number, ctx.tax_year
                ),
                entry_type=EntryType.TJE,
                description=f"Fines/penalties addback per IRC §162(f) — {row.account.account_name}",
                legs=(
                    JournalLeg(account=M1_ADDBACK_ACCOUNT, debit=amt, credit=Decimal("0")),
                    JournalLeg(account=row.account, debit=Decimal("0"), credit=amt),
                ),
                status=EntryStatus.PROPOSED,
                template_id=self.template_id,
            ))
        return out


class TaxExemptInterest(_TemplateBase):
    """Tax-exempt interest per IRC §103: book income, no tax income."""

    def __init__(self) -> None:
        super().__init__(
            template_id="tax_exempt_interest",
            schedule_m1_line="M-1 Line 7 (tax-exempt interest)",
            schedule_m3_line="M-3 Part II Line 5",
        )

    def propose(self, ctx: TemplateContext) -> list[JournalEntryAdjustment]:
        out = []
        for row in _find_rows_by_name_contains(ctx, "tax-exempt", "tax exempt", "municipal"):
            amt = row.unadjusted
            if amt == 0:
                continue
            out.append(JournalEntryAdjustment(
                entry_id=deterministic_entry_id(
                    self.template_id, row.account.account_number, ctx.tax_year
                ),
                entry_type=EntryType.TJE,
                description=f"Tax-exempt interest removed for tax — {row.account.account_name}",
                legs=(
                    JournalLeg(account=row.account, debit=amt, credit=Decimal("0")),
                    JournalLeg(account=M1_ADDBACK_ACCOUNT, debit=Decimal("0"), credit=amt),
                ),
                status=EntryStatus.PROPOSED,
                template_id=self.template_id,
            ))
        return out


STARTER_LIBRARY_2025 = [
    MealsFiftyPercentLimit(),
    EntertainmentDisallowance(),
    FinesAndPenaltiesAddback(),
    TaxExemptInterest(),
]
