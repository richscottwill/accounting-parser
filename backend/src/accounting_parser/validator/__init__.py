"""Validator: pure-function checks over ParseResult / WorkingTrialBalance.

Every validator returns a list of ``Finding`` records. Zero findings means
the input satisfies every rule. Findings carry severity (info, warning,
error, blocker), rule_id, expected/observed values, tolerance, and
source references.

Design reference: design.md §3.5 + requirements R9.1-R9.7.
"""

from accounting_parser.validator.findings import Finding, Severity
from accounting_parser.validator.rules import (
    DEFAULT_TOLERANCE,
    validate_ap_aging,
    validate_ar_aging,
    validate_balance_sheet_ties,
    validate_bank_statement,
    validate_parse_result,
    validate_subtotals_foot,
    validate_trial_balance,
    validate_wtb_tie_out,
)

__all__ = [
    "Finding",
    "Severity",
    "DEFAULT_TOLERANCE",
    "validate_parse_result",
    "validate_trial_balance",
    "validate_balance_sheet_ties",
    "validate_subtotals_foot",
    "validate_ar_aging",
    "validate_ap_aging",
    "validate_bank_statement",
    "validate_wtb_tie_out",
]
