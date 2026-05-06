"""ASC 740 deferred tax module (C-corps only, federal).

Permanent vs temporary difference tracking, DTA/DTL rollforward from
prior-year balances, effective tax rate reconciliation.

Scope at MVP: federal only, C-corporations only (Form 1120). State
deferred tax, S-corps, partnerships deferred.
"""

from accounting_parser.asc740.calculator import (
    DTASchedule,
    DeferredTaxRollforward,
    EffectiveTaxRateRecon,
    TemporaryDifference,
    classify_difference,
    compute_deferred_tax_rollforward,
    compute_etr_recon,
)

__all__ = [
    "TemporaryDifference",
    "DTASchedule",
    "DeferredTaxRollforward",
    "EffectiveTaxRateRecon",
    "classify_difference",
    "compute_deferred_tax_rollforward",
    "compute_etr_recon",
]
