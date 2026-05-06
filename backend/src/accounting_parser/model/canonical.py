"""Canonical Financial Model — Pydantic v2 models.

Every top-level record (``ParseResult``, ``WorkingTrialBalance``,
``FixedAsset``, ``TaxFormField``, ``JournalEntryAdjustment``, ``Account``,
``ReportSection``, ``PayrollRecord``) has a ``schema_version`` field.

All monetary values use ``Decimal``. All timestamps are timezone-aware UTC.
All UUIDs are canonical string form in serialized output.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


# Current schema version. Bump when any model field changes incompatibly.
SchemaVersion = Literal[1]
CURRENT_SCHEMA_VERSION: SchemaVersion = 1


class _Model(BaseModel):
    """Base for every canonical model.

    - ``extra='forbid'`` prevents silent field drift during schema changes.
    - ``frozen=True`` makes instances hashable and cache-safe.
    - ``str_strip_whitespace=True`` normalizes incoming text.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


# ---------------------------------------------------------------------------
# Source provenance
# ---------------------------------------------------------------------------

class BoundingBox(_Model):
    """Rectangular region within a source PDF page."""

    page: int = Field(ge=1)
    x0: Decimal
    y0: Decimal
    x1: Decimal
    y1: Decimal

    @field_validator("x1")
    @classmethod
    def _x1_gte_x0(cls, v: Decimal, info) -> Decimal:
        if "x0" in info.data and v < info.data["x0"]:
            raise ValueError("x1 must be >= x0")
        return v


class SourceRef(_Model):
    """Pointer to the source bytes for a parsed value."""

    document_id: UUID
    page_number: int | None = Field(default=None, ge=1)
    bounding_box: BoundingBox | None = None
    sheet_name: str | None = None
    cell_ref: str | None = None


# ---------------------------------------------------------------------------
# Accounts, reports
# ---------------------------------------------------------------------------

class AccountType(str, Enum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"
    GAIN = "gain"
    LOSS = "loss"
    OTHER = "other"


class NormalBalance(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class Account(_Model):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    account_number: str = Field(min_length=1, max_length=64)
    account_name: str = Field(min_length=1, max_length=255)
    account_type: AccountType | None = None
    normal_balance: NormalBalance | None = None
    category: str | None = None  # Classifier output
    category_confidence: Decimal | None = Field(default=None, ge=0, le=1)


class ReportLine(_Model):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    line_id: str
    account: Account
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    balance: Decimal = Decimal("0")
    source_ref: SourceRef | None = None
    displayed_value: str | None = None  # original string, e.g. "(1,234.56)"
    ocr_confidence: Decimal | None = Field(default=None, ge=0, le=1)


class ReportSection(_Model):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    section_id: str
    title: str
    lines: tuple[ReportLine, ...] = ()
    subsections: tuple["ReportSection", ...] = ()


# ---------------------------------------------------------------------------
# Journal entries
# ---------------------------------------------------------------------------

class EntryType(str, Enum):
    AJE = "aje"
    RJE = "rje"
    TJE = "tje"
    ELIM = "elim"


class EntryStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    POSTED = "posted"
    REJECTED = "rejected"
    REVERSED = "reversed"


class JournalLeg(_Model):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    account: Account
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    memo: str | None = None


class JournalEntryAdjustment(_Model):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    entry_id: UUID
    entry_type: EntryType
    description: str
    legs: tuple[JournalLeg, ...]
    status: EntryStatus = EntryStatus.PROPOSED
    template_id: str | None = None
    posted_at: datetime | None = None


# ---------------------------------------------------------------------------
# Fixed assets
# ---------------------------------------------------------------------------

class DepreciationMethod(str, Enum):
    STRAIGHT_LINE = "straight_line"
    MACRS_HY = "macrs_half_year"
    MACRS_MQ = "macrs_mid_quarter"
    MACRS_MM = "macrs_mid_month"


class FixedAsset(_Model):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    asset_id: str
    description: str
    class_life: int = Field(ge=1, le=50)
    placed_in_service: datetime
    cost_basis: Decimal = Field(ge=0)
    section_179: Decimal = Field(default=Decimal("0"), ge=0)
    bonus_rate: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    book_method: DepreciationMethod = DepreciationMethod.STRAIGHT_LINE
    tax_method: DepreciationMethod = DepreciationMethod.MACRS_HY
    disposed_at: datetime | None = None


# ---------------------------------------------------------------------------
# Tax forms, payroll
# ---------------------------------------------------------------------------

class TaxFormField(_Model):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    form_id: str
    box_id: str
    value: str
    normalized_value: Decimal | None = None
    ocr_confidence: Decimal | None = Field(default=None, ge=0, le=1)
    source_ref: SourceRef | None = None
    gate_confirmed: bool = False  # R4.24 field-validation gate


class PayrollRecord(_Model):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    period_start: datetime
    period_end: datetime
    employee_count: int = Field(ge=0)
    gross_wages: Decimal = Field(ge=0)
    federal_withholding: Decimal = Field(default=Decimal("0"), ge=0)


# ---------------------------------------------------------------------------
# Top-level aggregates
# ---------------------------------------------------------------------------

class ReportType(str, Enum):
    TRIAL_BALANCE = "trial_balance"
    GENERAL_LEDGER = "general_ledger"
    BALANCE_SHEET = "balance_sheet"
    INCOME_STATEMENT = "income_statement"
    CASH_FLOW = "cash_flow"
    BANK_STATEMENT = "bank_statement"
    AR_AGING = "ar_aging"
    AP_AGING = "ap_aging"
    FIXED_ASSET_SCHEDULE = "fixed_asset_schedule"
    TAX_FORM = "tax_form"
    PAYROLL = "payroll"
    OTHER = "other"


class ParseResult(_Model):
    """Output of a parser run against a single Document."""

    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    document_id: UUID
    report_type: ReportType
    source_system: str | None = None
    source_confidence: Decimal | None = Field(default=None, ge=0, le=1)
    parser_version: str
    parsed_at: datetime
    sections: tuple[ReportSection, ...] = ()
    fixed_assets: tuple[FixedAsset, ...] = ()
    tax_form_fields: tuple[TaxFormField, ...] = ()
    payroll_records: tuple[PayrollRecord, ...] = ()


class WTBRow(_Model):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    account: Account
    prior_year: Decimal = Decimal("0")
    unadjusted: Decimal = Decimal("0")
    sum_aje: Decimal = Decimal("0")
    adjusted: Decimal = Decimal("0")
    sum_rje: Decimal = Decimal("0")
    final: Decimal = Decimal("0")
    sum_tje: Decimal = Decimal("0")
    tax_basis: Decimal = Decimal("0")


class WorkingTrialBalance(_Model):
    schema_version: SchemaVersion = CURRENT_SCHEMA_VERSION
    engagement_id: UUID
    rows: tuple[WTBRow, ...] = ()
