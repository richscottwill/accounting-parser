"""ASC 740 computations: DTA/DTL rollforward + ETR reconciliation.

Simplified model: every TemporaryDifference carries book vs tax basis
deltas and a recognition direction (DTA increases vs DTL increases).
Applied federal statutory rate to produce the deferred tax balance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum


class DifferenceDirection(str, Enum):
    """Whether the book-vs-tax basis difference creates a future deductible
    amount (DTA) or future taxable amount (DTL)."""

    DTA = "deferred_tax_asset"
    DTL = "deferred_tax_liability"


@dataclass(frozen=True)
class TemporaryDifference:
    """One permanent or temporary difference line item."""

    name: str
    book_amount: Decimal
    tax_amount: Decimal
    direction: DifferenceDirection
    is_permanent: bool = False

    @property
    def delta(self) -> Decimal:
        return self.book_amount - self.tax_amount


@dataclass(frozen=True)
class DeferredTaxRollforward:
    """One line of the DTA/DTL rollforward schedule."""

    label: str
    beginning_balance: Decimal
    additions: Decimal
    reversals: Decimal

    @property
    def ending_balance(self) -> Decimal:
        return self.beginning_balance + self.additions - self.reversals


@dataclass(frozen=True)
class DTASchedule:
    rollforwards: tuple[DeferredTaxRollforward, ...]
    statutory_rate: Decimal

    @property
    def total_beginning(self) -> Decimal:
        return sum((r.beginning_balance for r in self.rollforwards), Decimal("0"))

    @property
    def total_ending(self) -> Decimal:
        return sum((r.ending_balance for r in self.rollforwards), Decimal("0"))


@dataclass(frozen=True)
class EffectiveTaxRateRecon:
    """Effective tax rate reconciliation schedule."""

    pretax_book_income: Decimal
    statutory_rate: Decimal
    permanent_differences: Decimal  # added back for tax
    current_tax_expense: Decimal
    deferred_tax_expense: Decimal

    @property
    def statutory_tax(self) -> Decimal:
        return (self.pretax_book_income * self.statutory_rate).quantize(Decimal("0.01"))

    @property
    def tax_on_permanents(self) -> Decimal:
        return (self.permanent_differences * self.statutory_rate).quantize(Decimal("0.01"))

    @property
    def total_tax_provision(self) -> Decimal:
        return self.current_tax_expense + self.deferred_tax_expense

    @property
    def effective_rate(self) -> Decimal:
        if self.pretax_book_income == 0:
            return Decimal("0")
        return (self.total_tax_provision / self.pretax_book_income).quantize(
            Decimal("0.0001")
        )


def classify_difference(diff: TemporaryDifference) -> str:
    """Return a human-readable classification."""
    if diff.is_permanent:
        return "permanent"
    return "temporary_dta" if diff.direction == DifferenceDirection.DTA else "temporary_dtl"


def compute_deferred_tax_rollforward(
    prior_balances: dict[str, Decimal],
    current_year_additions: dict[str, Decimal],
    current_year_reversals: dict[str, Decimal],
    *,
    statutory_rate: Decimal = Decimal("0.21"),
) -> DTASchedule:
    """Produce a DTA/DTL rollforward schedule.

    ``prior_balances``, ``additions``, ``reversals`` are keyed by difference
    name. All values in dollars (not pre-rate). The output schedule is
    also in dollars — multiplying by the rate is the caller's
    responsibility (shown in ETR recon).
    """
    all_names = set(prior_balances) | set(current_year_additions) | set(current_year_reversals)
    rolls: list[DeferredTaxRollforward] = []
    for name in sorted(all_names):
        rolls.append(DeferredTaxRollforward(
            label=name,
            beginning_balance=prior_balances.get(name, Decimal("0")),
            additions=current_year_additions.get(name, Decimal("0")),
            reversals=current_year_reversals.get(name, Decimal("0")),
        ))
    return DTASchedule(rollforwards=tuple(rolls), statutory_rate=statutory_rate)


def compute_etr_recon(
    pretax_book_income: Decimal,
    permanent_differences: Decimal,
    current_tax_expense: Decimal,
    deferred_tax_expense: Decimal,
    *,
    statutory_rate: Decimal = Decimal("0.21"),
) -> EffectiveTaxRateRecon:
    """Compute the effective tax rate reconciliation schedule."""
    return EffectiveTaxRateRecon(
        pretax_book_income=pretax_book_income,
        statutory_rate=statutory_rate,
        permanent_differences=permanent_differences,
        current_tax_expense=current_tax_expense,
        deferred_tax_expense=deferred_tax_expense,
    )
