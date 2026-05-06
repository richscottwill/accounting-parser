"""Year-over-year rollforward: close prior Engagement, open new with
prior ending balances as new beginning balances.

Identity match key: ``(tenant_id, client_id, account_number)`` — preserves
account identity across engagements (R19.1).
"""

from accounting_parser.rollforward.engine import (
    Carryforwards,
    RollforwardResult,
    rollforward,
)

__all__ = ["rollforward", "RollforwardResult", "Carryforwards"]
