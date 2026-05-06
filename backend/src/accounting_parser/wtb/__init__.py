"""Working Trial Balance engine.

Single entry point ``apply_change`` that accepts a tagged-union Change
and produces a new WorkingTrialBalance. Derived columns (adjusted, final,
tax_basis) are recomputed on every mutation. Tie-out invariant is
enforced: unadjusted + sum_aje == adjusted within tolerance.

Design reference: design.md §3.6, requirements R11.1-R11.8.
"""

from accounting_parser.wtb.engine import (
    PostEntryChange,
    RemoveEntryChange,
    SetUnadjustedChange,
    apply_change,
    TieOutViolation,
)

__all__ = [
    "apply_change",
    "PostEntryChange",
    "RemoveEntryChange",
    "SetUnadjustedChange",
    "TieOutViolation",
]
