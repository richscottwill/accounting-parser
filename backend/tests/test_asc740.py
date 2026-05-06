"""ASC 740 module tests."""

from __future__ import annotations

from decimal import Decimal

from accounting_parser.asc740 import (
    compute_deferred_tax_rollforward,
    compute_etr_recon,
)


def test_dta_rollforward_math() -> None:
    result = compute_deferred_tax_rollforward(
        prior_balances={"depreciation_difference": Decimal("50000")},
        current_year_additions={"depreciation_difference": Decimal("10000"),
                                "nol": Decimal("5000")},
        current_year_reversals={"depreciation_difference": Decimal("3000")},
    )
    # Sorted alphabetically: depreciation_difference first
    assert result.rollforwards[0].label == "depreciation_difference"
    assert result.rollforwards[0].beginning_balance == Decimal("50000")
    assert result.rollforwards[0].ending_balance == Decimal("57000")

    assert result.rollforwards[1].label == "nol"
    assert result.rollforwards[1].beginning_balance == Decimal("0")
    assert result.rollforwards[1].ending_balance == Decimal("5000")

    assert result.total_beginning == Decimal("50000")
    assert result.total_ending == Decimal("62000")


def test_etr_recon_happy_path() -> None:
    recon = compute_etr_recon(
        pretax_book_income=Decimal("1000000"),
        permanent_differences=Decimal("50000"),
        current_tax_expense=Decimal("200000"),
        deferred_tax_expense=Decimal("15000"),
    )
    # Statutory tax at 21% = $210,000
    assert recon.statutory_tax == Decimal("210000.00")
    # Permanent differences at 21% = $10,500
    assert recon.tax_on_permanents == Decimal("10500.00")
    # Total provision = current + deferred = $215,000
    assert recon.total_tax_provision == Decimal("215000")
    # ETR = 215k / 1000k = 21.5%
    assert recon.effective_rate == Decimal("0.2150")


def test_zero_income_etr_is_zero() -> None:
    recon = compute_etr_recon(
        pretax_book_income=Decimal("0"),
        permanent_differences=Decimal("0"),
        current_tax_expense=Decimal("0"),
        deferred_tax_expense=Decimal("0"),
    )
    assert recon.effective_rate == Decimal("0")
