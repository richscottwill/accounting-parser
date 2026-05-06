"""Canonical Financial Model — Pydantic models for every domain entity.

Design reference: design.md §2.2.

Every top-level record carries a ``schema_version`` field so we can evolve
the model without breaking stored payloads. Migrations follow the contract
``migrate_v<N>_to_v<N+1>(record) -> record`` in ``model.migrations``.
"""

from accounting_parser.model.canonical import (
    Account,
    BoundingBox,
    FixedAsset,
    JournalEntryAdjustment,
    JournalLeg,
    ParseResult,
    PayrollRecord,
    ReportLine,
    ReportSection,
    SchemaVersion,
    TaxFormField,
    WorkingTrialBalance,
)
from accounting_parser.model.pretty_printer import (
    canonical_json,
    equals_under_equivalence,
    parse_canonical_json,
)

__all__ = [
    "SchemaVersion",
    "Account",
    "ReportSection",
    "ReportLine",
    "JournalEntryAdjustment",
    "JournalLeg",
    "FixedAsset",
    "TaxFormField",
    "PayrollRecord",
    "BoundingBox",
    "ParseResult",
    "WorkingTrialBalance",
    "canonical_json",
    "parse_canonical_json",
    "equals_under_equivalence",
]
