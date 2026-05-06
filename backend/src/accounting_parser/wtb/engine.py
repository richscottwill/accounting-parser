"""Working Trial Balance apply_change engine.

Change is a tagged union. Every apply_change call:
1. Applies the change to the WTB
2. Recomputes derived columns (adjusted, final, tax_basis)
3. Enforces the tie-out invariant
4. Returns the new WTB or raises TieOutViolation

Frozen Pydantic models mean we always produce a new instance, never
mutate in place.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Union

from accounting_parser.model.canonical import (
    Account,
    EntryType,
    JournalEntryAdjustment,
    WorkingTrialBalance,
    WTBRow,
)


DEFAULT_TOLERANCE: Decimal = Decimal("0.01")


class TieOutViolation(Exception):
    """Raised when an apply_change would produce a WTB that fails the tie-out."""


@dataclass(frozen=True)
class SetUnadjustedChange:
    """Set the unadjusted column for an account (e.g., from a fresh TB import)."""

    account_number: str
    account: Account
    unadjusted: Decimal


@dataclass(frozen=True)
class PostEntryChange:
    """Post a journal entry to the appropriate AJE/RJE/TJE column."""

    entry: JournalEntryAdjustment


@dataclass(frozen=True)
class RemoveEntryChange:
    """Reverse a previously-posted entry."""

    entry: JournalEntryAdjustment


Change = Union[SetUnadjustedChange, PostEntryChange, RemoveEntryChange]


def _row_by_account(wtb: WorkingTrialBalance, account_number: str) -> WTBRow | None:
    for r in wtb.rows:
        if r.account.account_number == account_number:
            return r
    return None


def _recompute_derived(row: WTBRow) -> WTBRow:
    """Apply the R11.5 formulas: adjusted = unadjusted + sum_aje, etc."""
    adjusted = row.unadjusted + row.sum_aje
    final = adjusted + row.sum_rje
    tax_basis = final + row.sum_tje
    return row.model_copy(update={
        "adjusted": adjusted,
        "final": final,
        "tax_basis": tax_basis,
    })


def _apply_set_unadjusted(
    wtb: WorkingTrialBalance, change: SetUnadjustedChange
) -> WorkingTrialBalance:
    rows = list(wtb.rows)
    existing = _row_by_account(wtb, change.account_number)
    if existing is None:
        new_row = WTBRow(
            account=change.account,
            unadjusted=change.unadjusted,
        )
        new_row = _recompute_derived(new_row)
        rows.append(new_row)
    else:
        updated = existing.model_copy(update={"unadjusted": change.unadjusted})
        updated = _recompute_derived(updated)
        rows = [r if r.account.account_number != change.account_number else updated
                for r in rows]
    return wtb.model_copy(update={"rows": tuple(rows)})


def _entry_sum_column(entry_type: EntryType) -> str:
    return {
        EntryType.AJE: "sum_aje",
        EntryType.RJE: "sum_rje",
        EntryType.TJE: "sum_tje",
        EntryType.ELIM: "sum_aje",  # elim posted as AJE-type for column purposes
    }[entry_type]


def _apply_entry(
    wtb: WorkingTrialBalance, entry: JournalEntryAdjustment, *, reverse: bool
) -> WorkingTrialBalance:
    col = _entry_sum_column(entry.entry_type)
    sign = Decimal("-1") if reverse else Decimal("1")
    rows_by_num = {r.account.account_number: r for r in wtb.rows}
    for leg in entry.legs:
        num = leg.account.account_number
        row = rows_by_num.get(num)
        if row is None:
            # Auto-create a zero-unadjusted row for this account
            row = WTBRow(account=leg.account)
        # Debit increases the column total; credit decreases (book convention)
        delta = (leg.debit - leg.credit) * sign
        updated = row.model_copy(update={col: getattr(row, col) + delta})
        updated = _recompute_derived(updated)
        rows_by_num[num] = updated
    return wtb.model_copy(update={"rows": tuple(rows_by_num.values())})


def _enforce_tie_out(wtb: WorkingTrialBalance, tolerance: Decimal) -> None:
    """Per R11.5: every row's unadjusted + sum_aje == adjusted, etc.

    Since ``_recompute_derived`` computes the RHS from the LHS, this will
    only trip if someone bypasses the engine. It's a safety net, not
    the primary check.
    """
    for row in wtb.rows:
        if abs((row.unadjusted + row.sum_aje) - row.adjusted) > tolerance:
            raise TieOutViolation(
                f"WTB row for {row.account.account_number!r}: "
                f"unadjusted {row.unadjusted} + sum_aje {row.sum_aje} "
                f"!= adjusted {row.adjusted}"
            )


def apply_change(
    wtb: WorkingTrialBalance,
    change: Change,
    *,
    tolerance: Decimal = DEFAULT_TOLERANCE,
) -> WorkingTrialBalance:
    """Apply one Change to the WTB and return the new WTB.

    Raises ``TieOutViolation`` if the derived columns fall out of tie-out
    (Correctness Property 12).
    """
    if isinstance(change, SetUnadjustedChange):
        new_wtb = _apply_set_unadjusted(wtb, change)
    elif isinstance(change, PostEntryChange):
        new_wtb = _apply_entry(wtb, change.entry, reverse=False)
    elif isinstance(change, RemoveEntryChange):
        new_wtb = _apply_entry(wtb, change.entry, reverse=True)
    else:
        raise TypeError(f"unknown Change type: {type(change).__name__}")
    _enforce_tie_out(new_wtb, tolerance)
    return new_wtb
