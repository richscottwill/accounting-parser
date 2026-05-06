"""Tax-year-scoped depreciation parameters.

Encapsulates Section 179 limits, bonus depreciation rates, MACRS class-life
tables, and convention rules. Bump ``TAX_YEAR_PARAMETERS`` for each new
tax year.

Sources:
- IRS Rev. Proc. for annual Section 179 limits
- IRS Publication 946 for MACRS tables and conventions
- OBBBA (One Big Beautiful Bill Act, 2025) for bonus depreciation
  100% restoration effective for property placed in service
  ON OR AFTER January 20, 2025. Before that cutoff in 2025, the
  phase-down rate of 40% applies.

This implementation encodes only what the Depreciation Engine actually
needs. It is NOT a complete tax-code reference.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


OBBBA_EFFECTIVE_DATE = date(2025, 1, 20)


@dataclass(frozen=True)
class TaxYearParameterSet:
    tax_year: int
    section_179_limit: Decimal
    section_179_phase_out_start: Decimal
    bonus_rate_default: Decimal  # applies when no date override needed
    # Date-conditional overrides for bonus. Each tuple is (cutoff, before_rate, on_or_after_rate).
    bonus_rate_date_splits: tuple[tuple[date, Decimal, Decimal], ...] = ()
    macrs_class_lives: tuple[int, ...] = (3, 5, 7, 10, 15, 20, 27, 39)


TAX_YEAR_PARAMETERS: dict[int, TaxYearParameterSet] = {
    2023: TaxYearParameterSet(
        tax_year=2023,
        section_179_limit=Decimal("1160000"),
        section_179_phase_out_start=Decimal("2890000"),
        bonus_rate_default=Decimal("0.80"),
    ),
    2024: TaxYearParameterSet(
        tax_year=2024,
        section_179_limit=Decimal("1160000"),
        section_179_phase_out_start=Decimal("2890000"),
        bonus_rate_default=Decimal("0.60"),
    ),
    2025: TaxYearParameterSet(
        tax_year=2025,
        section_179_limit=Decimal("1220000"),
        section_179_phase_out_start=Decimal("3050000"),
        bonus_rate_default=Decimal("0.40"),
        bonus_rate_date_splits=(
            (OBBBA_EFFECTIVE_DATE, Decimal("0.40"), Decimal("1.00")),
        ),
    ),
    2026: TaxYearParameterSet(
        tax_year=2026,
        section_179_limit=Decimal("1250000"),
        section_179_phase_out_start=Decimal("3125000"),
        bonus_rate_default=Decimal("1.00"),  # assume OBBBA holds
    ),
}


def get_tax_year_parameters(tax_year: int) -> TaxYearParameterSet:
    if tax_year not in TAX_YEAR_PARAMETERS:
        raise KeyError(
            f"No parameter set registered for tax year {tax_year}. "
            f"Supported: {sorted(TAX_YEAR_PARAMETERS)}"
        )
    return TAX_YEAR_PARAMETERS[tax_year]


def bonus_rate_for(placed_in_service: date, tax_year: int) -> Decimal:
    """Return the applicable bonus depreciation rate given placed-in-service date.

    Handles OBBBA 2025: 40% before 2025-01-20, 100% on or after.
    """
    params = get_tax_year_parameters(tax_year)
    for cutoff, before, on_after in params.bonus_rate_date_splits:
        if placed_in_service < cutoff:
            return before
        return on_after
    return params.bonus_rate_default
