"""Shared realistic-looking account data used by multiple factories."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal


NormalBalance = Literal["debit", "credit"]


@dataclass(frozen=True)
class Account:
    """An account with deterministic fake numeric values."""

    number: str
    name: str
    type: str
    normal_balance: NormalBalance
    balance: Decimal


# Obvious-fake balances (Benford-adjacent patterns like 12,345.67) so accidental
# screenshot exposure is visually detectable.
DEFAULT_CHART: tuple[Account, ...] = (
    Account("1000", "Cash - Operating", "Asset", "debit", Decimal("123456.78")),
    Account("1010", "Cash - Payroll", "Asset", "debit", Decimal("23456.78")),
    Account("1100", "Accounts Receivable", "Asset", "debit", Decimal("234567.89")),
    Account("1150", "Allowance for Doubtful Accounts", "Asset", "credit", Decimal("12345.67")),
    Account("1200", "Inventory", "Asset", "debit", Decimal("345678.90")),
    Account("1500", "Prepaid Expenses", "Asset", "debit", Decimal("12345.67")),
    Account("1700", "Fixed Assets - Equipment", "Asset", "debit", Decimal("567890.12")),
    Account("1710", "Accumulated Depreciation - Equipment", "Asset", "credit", Decimal("123456.78")),
    Account("2000", "Accounts Payable", "Liability", "credit", Decimal("123456.78")),
    Account("2100", "Accrued Expenses", "Liability", "credit", Decimal("23456.78")),
    Account("2200", "Payroll Liabilities", "Liability", "credit", Decimal("12345.67")),
    Account("2500", "Long-Term Debt", "Liability", "credit", Decimal("234567.89")),
    Account("3000", "Common Stock", "Equity", "credit", Decimal("100000.00")),
    Account("3100", "Retained Earnings", "Equity", "credit", Decimal("456789.01")),
    Account("4000", "Revenue - Services", "Revenue", "credit", Decimal("1234567.89")),
    Account("4100", "Revenue - Products", "Revenue", "credit", Decimal("234567.89")),
    Account("5000", "Cost of Goods Sold", "Expense", "debit", Decimal("567890.12")),
    Account("6000", "Salaries & Wages", "Expense", "debit", Decimal("345678.90")),
    Account("6100", "Rent Expense", "Expense", "debit", Decimal("78901.23")),
    Account("6200", "Meals & Entertainment", "Expense", "debit", Decimal("12345.67")),
    Account("6300", "Professional Fees", "Expense", "debit", Decimal("34567.89")),
    Account("6400", "Depreciation Expense", "Expense", "debit", Decimal("56789.01")),
    Account("6500", "Office Supplies", "Expense", "debit", Decimal("8901.23")),
    Account("6600", "Travel Expense", "Expense", "debit", Decimal("23456.78")),
)


def balanced_debits_credits(accounts: tuple[Account, ...]) -> tuple[Decimal, Decimal]:
    """Compute total debits and credits from a chart.

    Returns ``(total_debits, total_credits)``. A balanced TB has the two equal.
    """
    debits = sum(
        (a.balance for a in accounts if a.normal_balance == "debit"), Decimal("0")
    )
    credits = sum(
        (a.balance for a in accounts if a.normal_balance == "credit"), Decimal("0")
    )
    return debits, credits
