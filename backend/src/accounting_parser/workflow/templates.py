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


def _register_defaults() -> None:
    register_template(monthly_close_bookkeeping)


# Register-on-import for the P1.4 shipped template. Future templates
# (individual_1040_prep, year_end_tax_prep) register here when they
# land in P2.
_register_defaults()
