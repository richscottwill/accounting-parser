"""Depreciation engine: Section 179 -> bonus -> MACRS with OBBBA 2025."""

from accounting_parser.depreciation.engine import (
    DepreciationResult,
    compute_year_one_depreciation,
)
from accounting_parser.depreciation.tax_year_parameters import (
    OBBBA_EFFECTIVE_DATE,
    TaxYearParameterSet,
    bonus_rate_for,
    get_tax_year_parameters,
)

__all__ = [
    "compute_year_one_depreciation",
    "DepreciationResult",
    "TaxYearParameterSet",
    "OBBBA_EFFECTIVE_DATE",
    "bonus_rate_for",
    "get_tax_year_parameters",
]
