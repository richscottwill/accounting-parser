"""PBC (Provided-By-Client) request management — parent Task 23.

Canonical PBC_Category list + request lifecycle state machine. The
Client Portal UI + magic-link auth already ship in P1.1; this module
adds the domain model + lifecycle transitions that tie everything
together.

### Lifecycle

    not_requested → requested → received → under_review → accepted
                                                        → rejected_resubmit
                                         → waived

Transitions are validated by ``PbcRequest.transition_to`` — invalid
transitions raise rather than silently no-op.
"""

from accounting_parser.pbc.model import (
    CANONICAL_CATEGORIES,
    InvalidPbcTransitionError,
    PbcCategory,
    PbcRequest,
    PbcStatus,
)

__all__ = [
    "CANONICAL_CATEGORIES",
    "InvalidPbcTransitionError",
    "PbcCategory",
    "PbcRequest",
    "PbcStatus",
]
