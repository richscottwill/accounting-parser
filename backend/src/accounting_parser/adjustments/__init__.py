"""Adjustment engine + Adjustment_Library.

Tax-year-scoped templates that produce proposed Journal Entry Adjustments
for common book-to-tax M-1/M-3 adjustments.
"""

from accounting_parser.adjustments.engine import (
    AdjustmentTemplate,
    TemplateContext,
    run_book_to_tax,
)
from accounting_parser.adjustments.library_2025 import STARTER_LIBRARY_2025

__all__ = [
    "AdjustmentTemplate",
    "TemplateContext",
    "run_book_to_tax",
    "STARTER_LIBRARY_2025",
]
