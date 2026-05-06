"""Depreciation engine property tests — Correctness Property 19 + OBBBA regression.

- 500 random FixedAssets: bonus rate is 40% for pre-2025-01-20 placed-in-
  service, 100% for on-or-after.
- Section 179 applied before bonus, bonus applied before MACRS (the
  three-stage ordering invariant).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from accounting_parser.depreciation import (
    OBBBA_EFFECTIVE_DATE,
    bonus_rate_for,
    compute_year_one_depreciation,
    get_tax_year_parameters,
)
from accounting_parser.model.canonical import (
    DepreciationMethod,
    FixedAsset,
)


UTC = timezone.utc


@st.composite
def fixed_asset_2025_strategy(draw):
    """Assets placed in service across the whole 2025 calendar year."""
    pis = draw(st.dates(min_value=date(2025, 1, 1), max_value=date(2025, 12, 31)))
    cost = draw(st.decimals(min_value=Decimal("100"), max_value=Decimal("200000"), places=2))
    section_179 = draw(st.decimals(
        min_value=Decimal("0"),
        max_value=min(cost, Decimal("50000")),
        places=2,
    ))
    class_life = draw(st.sampled_from([3, 5, 7, 10, 15, 20, 27, 39]))
    return FixedAsset(
        asset_id=f"FA-{pis.isoformat()}",
        description="test asset",
        class_life=class_life,
        placed_in_service=datetime.combine(pis, datetime.min.time(), tzinfo=UTC),
        cost_basis=cost,
        section_179=section_179,
        bonus_rate=Decimal("0"),  # engine overrides via TaxYearParameterSet
        book_method=DepreciationMethod.STRAIGHT_LINE,
        tax_method=DepreciationMethod.MACRS_HY,
    )


@given(fixed_asset_2025_strategy())
@settings(max_examples=500, deadline=None)
def test_obbba_bonus_rate_date_split(asset: FixedAsset) -> None:
    """For 2025: pre-2025-01-20 bonus = 40%, on-or-after = 100%."""
    pis = asset.placed_in_service.date()
    rate = bonus_rate_for(pis, 2025)
    if pis < OBBBA_EFFECTIVE_DATE:
        assert rate == Decimal("0.40"), f"pre-OBBBA on {pis}: expected 0.40, got {rate}"
    else:
        assert rate == Decimal("1.00"), f"post-OBBBA on {pis}: expected 1.00, got {rate}"


@given(fixed_asset_2025_strategy())
@settings(max_examples=500, deadline=None)
def test_three_stage_ordering(asset: FixedAsset) -> None:
    """Correctness Property 19: Section 179 -> bonus -> MACRS.

    Verify by computing each stage's basis:
      post_179_basis == cost - section_179
      bonus == post_179_basis * bonus_rate
      remaining == post_179_basis - bonus
      macrs_y1 == remaining * class_life_factor
    """
    result = compute_year_one_depreciation(asset, tax_year=2025)

    assert result.section_179_taken == asset.section_179
    post_179 = asset.cost_basis - asset.section_179
    rate = bonus_rate_for(asset.placed_in_service.date(), 2025)
    expected_bonus = (post_179 * rate).quantize(Decimal("0.01"))
    assert result.bonus_depreciation == expected_bonus
    assert result.remaining_basis_after_bonus == post_179 - expected_bonus


def test_non_obbba_year_has_no_date_split() -> None:
    """2024 has no date split — bonus_rate is 60% regardless of placed-in-service."""
    for d in (date(2024, 1, 1), date(2024, 7, 1), date(2024, 12, 31)):
        assert bonus_rate_for(d, 2024) == Decimal("0.60")


def test_section_179_cannot_exceed_basis() -> None:
    """Computing depreciation with section_179 > cost_basis raises."""
    asset = FixedAsset(
        asset_id="X",
        description="bad",
        class_life=5,
        placed_in_service=datetime(2025, 6, 1, tzinfo=UTC),
        cost_basis=Decimal("100"),
        section_179=Decimal("200"),  # too big
    )
    with pytest.raises(ValueError, match="cannot exceed"):
        compute_year_one_depreciation(asset, tax_year=2025)


def test_tax_year_parameters_registry() -> None:
    assert get_tax_year_parameters(2025).bonus_rate_default == Decimal("0.40")
    assert get_tax_year_parameters(2026).bonus_rate_default == Decimal("1.00")
    import pytest
    with pytest.raises(KeyError):
        get_tax_year_parameters(1999)
