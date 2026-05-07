"""Built-in workflow templates.

Each template is a named sequence of steps with per-step configuration.
Firms clone + customize via future UI; the built-ins are the canonical
reference implementation.

The five templates required by Requirement 10.6:
- new_client_onboarding
- monthly_close_bookkeeping
- year_end_tax_prep
- engagement_review_and_deliver
- individual_1040_prep
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StepSpec:
    name: str
    step_type: str
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowTemplate:
    id: str
    description: str
    steps: tuple[StepSpec, ...]


_TEMPLATES: dict[str, WorkflowTemplate] = {}


def _register(t: WorkflowTemplate) -> None:
    _TEMPLATES[t.id] = t


def get_template(template_id: str) -> WorkflowTemplate:
    if template_id not in _TEMPLATES:
        raise KeyError(f"Unknown workflow template: {template_id!r}")
    return _TEMPLATES[template_id]


def list_templates() -> list[str]:
    return sorted(_TEMPLATES.keys())


# -- new_client_onboarding ----------------------------------------------

_register(
    WorkflowTemplate(
        id="new_client_onboarding",
        description=(
            "First-engagement bootstrap — request PBC list, ingest prior-year "
            "return, carryforward balances, capture Entity_Type + Tax_Year."
        ),
        steps=(
            StepSpec(name="request_pbc", step_type="notify_user",
                     config={"recipient": "client_portal"}),
            StepSpec(name="ingest_prior_return", step_type="ingest"),
            StepSpec(name="parse_prior_return", step_type="parse"),
            StepSpec(name="carryforward", step_type="rollforward_from_prior_year"),
            StepSpec(name="classify_coa", step_type="classify"),
            StepSpec(name="preparer_review", step_type="require_preparer_review"),
        ),
    )
)


# -- monthly_close_bookkeeping ------------------------------------------

_register(
    WorkflowTemplate(
        id="monthly_close_bookkeeping",
        description=(
            "Monthly close: parse + classify + validate bookkeeping export, "
            "propose month-end AJEs, route to preparer review."
        ),
        steps=(
            StepSpec(name="ingest_export", step_type="ingest"),
            StepSpec(name="parse", step_type="parse"),
            StepSpec(name="classify", step_type="classify"),
            StepSpec(name="validate", step_type="validate"),
            StepSpec(name="propose_aje", step_type="propose_aje"),
            StepSpec(name="preparer_review", step_type="require_preparer_review"),
            StepSpec(name="notify_client", step_type="notify_user",
                     config={"recipient": "client"}),
        ),
    )
)


# -- year_end_tax_prep --------------------------------------------------

_register(
    WorkflowTemplate(
        id="year_end_tax_prep",
        description=(
            "Flagship annual tax prep — rollforward, import TB, book-to-tax, "
            "fixed-asset depreciation, lead schedules, export to target, sign off."
        ),
        steps=(
            StepSpec(name="rollforward", step_type="rollforward_from_prior_year"),
            StepSpec(name="ingest_tb", step_type="ingest"),
            StepSpec(name="parse_tb", step_type="parse"),
            StepSpec(name="classify", step_type="classify"),
            StepSpec(name="validate", step_type="validate"),
            StepSpec(name="fixed_assets", step_type="compute_fixed_asset_depreciation"),
            StepSpec(name="book_to_tax", step_type="run_book_to_tax"),
            StepSpec(name="propose_aje", step_type="propose_aje"),
            StepSpec(name="propose_tje", step_type="propose_tje"),
            StepSpec(name="preparer_review", step_type="require_preparer_review"),
            StepSpec(name="generate_lead_schedules", step_type="generate_lead_schedules"),
            StepSpec(name="export", step_type="export_to_target_system",
                     config={"target_system": "cch_axcess_engagement"}),
            StepSpec(name="reviewer_signoff", step_type="require_reviewer_signoff"),
            StepSpec(name="deliver", step_type="deliver_to_client_portal"),
        ),
    )
)


# -- engagement_review_and_deliver --------------------------------------

_register(
    WorkflowTemplate(
        id="engagement_review_and_deliver",
        description=(
            "Gate every lead schedule behind Reviewer signoff; assemble "
            "deliverable package; push to client portal."
        ),
        steps=(
            StepSpec(name="reviewer_signoff", step_type="require_reviewer_signoff"),
            StepSpec(name="export", step_type="export_to_target_system"),
            StepSpec(name="deliver", step_type="deliver_to_client_portal"),
        ),
    )
)


# -- individual_1040_prep -----------------------------------------------

_register(
    WorkflowTemplate(
        id="individual_1040_prep",
        description=(
            "1040 source-document workflow — no WTB/AJE steps; parse IRS "
            "forms, field-validation gate, export to 1040 engine."
        ),
        steps=(
            StepSpec(name="ingest", step_type="ingest"),
            StepSpec(name="parse_forms", step_type="parse"),
            StepSpec(name="preparer_review", step_type="require_preparer_review"),
            StepSpec(name="export", step_type="export_to_target_system",
                     config={"target_system": "lacerte"}),
        ),
    )
)
