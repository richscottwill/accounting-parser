"""Workflow templates — named, ordered step lists.

Templates are code-defined, not DB-defined. Reasoning: a workflow
template is a contract between the orchestration layer and the
review flow the firm walks through. DB-editable templates would
require versioning, migration rules, and UI — scope creep for the
self-hosted fork's single-firm target.

### Shipped templates

- ``monthly_close_bookkeeping`` — P1.4 first template. Parse →
  classify → validate → require_preparer_review → post_adjustments
  → emit_export. Covers the ex-RSM monthly-close shape without the
  tax-prep-specific steps.

### Adding a template

1. Define a module-level ``WorkflowTemplate`` constant.
2. Call ``register_template(my_template)`` at import time.
3. Write an integration test that runs the template to completion
   with the default stub handlers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WorkflowStepDef:
    """One step within a template."""

    name: str  # unique within the template, used as context key
    step_type: str  # must be a registered step type
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowTemplate:
    """A named ordered list of steps."""

    id: str
    title: str
    steps: tuple[WorkflowStepDef, ...]
    # Set of entity types (engagement.engagement_type) this template
    # applies to. Empty set means applicable to any engagement type.
    applies_to_engagement_types: frozenset[str] = frozenset()


# ---- Template: monthly_close_bookkeeping ------------------------

monthly_close_bookkeeping = WorkflowTemplate(
    id="monthly_close_bookkeeping",
    title="Monthly Close — Bookkeeping",
    applies_to_engagement_types=frozenset({"bookkeeping"}),
    steps=(
        WorkflowStepDef(name="parse_source_docs", step_type="parse"),
        WorkflowStepDef(name="classify_accounts", step_type="classify"),
        WorkflowStepDef(name="validate_tb", step_type="validate"),
        WorkflowStepDef(
            name="preparer_review",
            step_type="require_preparer_review",
            config={
                "reason": ("Review proposed month-end accruals and AJEs before posting."),
            },
        ),
        WorkflowStepDef(name="post_adjustments", step_type="post_adjustments"),
        WorkflowStepDef(
            name="emit_cch_export",
            step_type="emit_export",
            config={"target": "cch_engagement"},
        ),
    ),
)


# ---- Registry --------------------------------------------------


_TEMPLATES: dict[str, WorkflowTemplate] = {}


def register_template(template: WorkflowTemplate) -> None:
    """Register a template by id; replaces any existing registration.

    Idempotent on re-import so tests can re-register freely without
    teardown. Production code is expected to register once at
    application startup via ``_register_defaults()`` below.
    """
    _TEMPLATES[template.id] = template


def get_template(template_id: str) -> WorkflowTemplate:
    """Look up a template by id. Raises KeyError for unknown ids."""
    return _TEMPLATES[template_id]


def all_templates() -> list[WorkflowTemplate]:
    return list(_TEMPLATES.values())


# ---- Template: individual_1040_prep (parent Task 22) ------------
#
# Simpler than monthly_close: no WTB, no lead schedules, no AJEs.
# Focus is on 1040 sub-parsers (W-2, 1099-*, K-1, 1098 mortgage) +
# field-validation gate + shape-preserving export.

individual_1040_prep = WorkflowTemplate(
    id="individual_1040_prep",
    title="Individual 1040 Preparation",
    applies_to_engagement_types=frozenset({"tax_return"}),
    steps=(
        WorkflowStepDef(name="parse_1040_docs", step_type="parse"),
        WorkflowStepDef(
            name="ocr_field_gate",
            step_type="require_preparer_review",
            config={
                "reason": "Confirm OCR-extracted fields from W-2 / 1099 / K-1 forms.",
            },
        ),
        WorkflowStepDef(name="validate_1040_fields", step_type="validate"),
        WorkflowStepDef(
            name="emit_1040_export",
            step_type="emit_export",
            config={"target": "lacerte_1040"},
        ),
    ),
)


# ---- Template: year_end_tax_prep (parent Task 26, flagship) -----

year_end_tax_prep = WorkflowTemplate(
    id="year_end_tax_prep",
    title="Year-End Tax Preparation",
    applies_to_engagement_types=frozenset({"tax_return"}),
    steps=(
        WorkflowStepDef(name="rollforward", step_type="parse"),
        WorkflowStepDef(name="parse_source_docs", step_type="parse"),
        WorkflowStepDef(name="classify_accounts", step_type="classify"),
        WorkflowStepDef(name="validate_tb", step_type="validate"),
        WorkflowStepDef(name="run_depreciation", step_type="post_adjustments"),
        WorkflowStepDef(name="run_book_to_tax", step_type="post_adjustments"),
        WorkflowStepDef(
            name="preparer_review",
            step_type="require_preparer_review",
            config={
                "reason": (
                    "Review proposed AJE/RJE/TJE entries and depreciation. "
                    "Approve to post; reject individual entries in the UI."
                ),
            },
        ),
        WorkflowStepDef(name="post_adjustments", step_type="post_adjustments"),
        WorkflowStepDef(
            name="reviewer_signoff",
            step_type="require_reviewer_signoff",
            config={
                "reason": (
                    "Review lead schedules + financials before export to "
                    "vendor system. HMAC signoff is append-only."
                ),
            },
        ),
        WorkflowStepDef(
            name="emit_cch_export",
            step_type="emit_export",
            config={"target": "cch_engagement"},
        ),
    ),
)


def _register_defaults() -> None:
    register_template(monthly_close_bookkeeping)
    register_template(individual_1040_prep)
    register_template(year_end_tax_prep)


# Register-on-import for the P1.4 shipped template. Future templates
# (individual_1040_prep, year_end_tax_prep) register here when they
# land in P2.
_register_defaults()
