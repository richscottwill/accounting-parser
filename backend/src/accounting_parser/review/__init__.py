"""Reviewer signoff with cryptographic binding.

Every ReviewSignoff carries an HMAC-SHA256 over (payload, reviewer_id,
timestamp). Signoffs are append-only — a reversal is a new signoff that
references the original by ID, never an edit.

Design reference: requirements R22.5.
"""

from accounting_parser.review.signoff import (
    ReviewSignoff,
    SignoffLevel,
    create_signoff,
    reverse_signoff,
    verify_signoff,
)

__all__ = [
    "ReviewSignoff",
    "SignoffLevel",
    "create_signoff",
    "verify_signoff",
    "reverse_signoff",
]
