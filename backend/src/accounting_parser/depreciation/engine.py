"""Depreciation computation.

Three-stage ordering per Correctness Property 19:
    1. Section 179 election (up to statutory limit and phase-out).
    2. Bonus depreciation (date-conditional rate via TaxYearParameterSet).
    3. Regular MACRS on the remaining basis.

Decimal throughout — no float anywhere in tax-affecting computation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from accounting_parser.model.canonical import FixedAsset
from accounting_parser.depreciation.tax_year_parameters import (
    bonus_rate_for,
    get_tax_year_parameters,
)


@dataclass(frozen=True)
class DepreciationResult:
    section_179_taken: Decimal
    bonus_depreciation: Decimal
    remaining_basis_after_bonus: Decimal
    regular_macrs_year_one: Decimal
    total_year_one: Decimal


# Simplified MACRS half-year-convention year-1 factor table.
# In production this expands to a full (class_life, year_in_life) lookup.
MACRS_HY_YEAR_ONE: dict[int, Decimal] = {
    3: Decimal("0.3333"),
    5: Decimal("0.2000"),
    7: Decimal("0.1429"),
    10: Decimal("0.1000"),
    15: Decimal("0.0500"),
    20: Decimal("0.0375"),
    27: Decimal("0.0303"),  # residential real property (SL, MM convention)
    39: Decimal("0.0214"),  # commercial real property (SL, MM convention)
}


def compute_year_one_depreciation(
    asset: FixedAsset, tax_year: int
) -> DepreciationResult:
    """Apply the Section 179 -> bonus -> MACRS pipeline for year one.

    Correctness Property 19: the ordering is fixed. Bonus rate comes from
    the TaxYearParameterSet applied to placed_in_service, so OBBBA 2025
    date-conditional logic is encapsulated in ``bonus_rate_for``.
    """
    # Stage 1: Section 179 (already elected on the FixedAsset model)
    section_179 = asset.section_179
    if section_179 > asset.cost_basis:
        raise ValueError(
            f"section_179 {section_179} cannot exceed cost_basis {asset.cost_basis}"
        )

    # Stage 2: bonus depreciation on the post-179 basis
    post_179_basis = asset.cost_basis - section_179
    pis_date = asset.placed_in_service.date() if hasattr(asset.placed_in_service, "date") \
        else asset.placed_in_service
    bonus_rate = bonus_rate_for(pis_date, tax_year)
    bonus = (post_179_basis * bonus_rate).quantize(Decimal("0.01"))

    # Stage 3: regular MACRS on the remainder
    remaining = post_179_basis - bonus
    year_one_factor = MACRS_HY_YEAR_ONE.get(asset.class_life, Decimal("0"))
    macrs_year_one = (remaining * year_one_factor).quantize(Decimal("0.01"))

    total = section_179 + bonus + macrs_year_one

    return DepreciationResult(
        section_179_taken=section_179,
        bonus_depreciation=bonus,
        remaining_basis_after_bonus=remaining,
        regular_macrs_year_one=macrs_year_one,
        total_year_one=total,
    )
