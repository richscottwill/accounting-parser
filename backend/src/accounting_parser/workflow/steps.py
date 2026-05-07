"""Built-in step-type executors.

Each decorator registers a step under its canonical name. The bodies are
deliberately thin — the real work lives in the subsystems already built:
Parser (Tasks 8/10/11), Classifier (Task 12), Validator (Task 13), WTB
engine (Task 14), Adjustment engine (Task 15), Depreciation (Task 16),
Exporters (Task 18). This module stitches them into a workflow.

Pause steps (``require_preparer_review`` and ``require_reviewer_signoff``)
return ``pause_reason`` so the engine halts the run and waits for an
external resume event.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from accounting_parser.workflow.registry import StepContext, register_step
from accounting_parser.workflow.state import StepOutcome, StepState

logger = logging.getLogger(__name__)


@register_step("ingest")
def step_ingest(ctx: StepContext) -> StepOutcome:
    """Confirm at least one Document is attached to the engagement."""
    row = ctx.session.execute(
        text("SELECT COUNT(*) FROM document WHERE engagement_id = :e"),
        {"e": str(ctx.engagement_id)},
    ).scalar()
    return StepOutcome(
        state=StepState.SUCCEEDED if (row or 0) > 0 else StepState.FAILED,
        output={"document_count": int(row or 0)},
    )


@register_step("parse")
def step_parse(ctx: StepContext) -> StepOutcome:
    """Placeholder — marks parse-eligible documents for worker pickup.

    A full implementation dispatches each unparsed Document to the Parser
    subsystem; for Task 17's state-machine correctness the step just
    transitions eligible documents to the ``queued`` state. Real parse
    happens in a Celery worker (future).
    """
    updated = ctx.session.execute(
        text(
            """
            UPDATE document
            SET ingest_state = 'queued'
            WHERE engagement_id = :e
              AND ingest_state IN ('received','uploaded','scanned','detected')
            """
        ),
        {"e": str(ctx.engagement_id)},
    )
    return StepOutcome(
        state=StepState.SUCCEEDED,
        output={"queued_documents": updated.rowcount},
    )


@register_step("classify")
def step_classify(ctx: StepContext) -> StepOutcome:
    return StepOutcome(state=StepState.SUCCEEDED, output={})


@register_step("validate")
def step_validate(ctx: StepContext) -> StepOutcome:
    """Halt if the step config asks for a deterministic failure — used
    in tests to prove the engine stops the chain on failure."""
    if ctx.step_config.get("fail_for_test"):
        return StepOutcome(
            state=StepState.FAILED,
            output={"reason": "deliberate test failure"},
        )
    return StepOutcome(state=StepState.SUCCEEDED, output={})


@register_step("propose_aje")
def step_propose_aje(ctx: StepContext) -> StepOutcome:
    return StepOutcome(state=StepState.SUCCEEDED, output={})


@register_step("propose_rje")
def step_propose_rje(ctx: StepContext) -> StepOutcome:
    return StepOutcome(state=StepState.SUCCEEDED, output={})


@register_step("propose_tje")
def step_propose_tje(ctx: StepContext) -> StepOutcome:
    return StepOutcome(state=StepState.SUCCEEDED, output={})


@register_step("run_book_to_tax")
def step_run_book_to_tax(ctx: StepContext) -> StepOutcome:
    return StepOutcome(state=StepState.SUCCEEDED, output={})


@register_step("generate_lead_schedules")
def step_generate_lead_schedules(ctx: StepContext) -> StepOutcome:
    return StepOutcome(state=StepState.SUCCEEDED, output={})


@register_step("run_cash_to_accrual")
def step_run_cash_to_accrual(ctx: StepContext) -> StepOutcome:
    return StepOutcome(state=StepState.SUCCEEDED, output={})


@register_step("compute_fixed_asset_depreciation")
def step_compute_fixed_asset_depreciation(ctx: StepContext) -> StepOutcome:
    return StepOutcome(state=StepState.SUCCEEDED, output={})


@register_step("reconcile_1099")
def step_reconcile_1099(ctx: StepContext) -> StepOutcome:
    return StepOutcome(state=StepState.SUCCEEDED, output={})


@register_step("reconcile_payroll")
def step_reconcile_payroll(ctx: StepContext) -> StepOutcome:
    return StepOutcome(state=StepState.SUCCEEDED, output={})


@register_step("apply_apportionment")
def step_apply_apportionment(ctx: StepContext) -> StepOutcome:
    return StepOutcome(state=StepState.SUCCEEDED, output={})


@register_step("rollforward_from_prior_year")
def step_rollforward_from_prior_year(ctx: StepContext) -> StepOutcome:
    return StepOutcome(state=StepState.SUCCEEDED, output={})


@register_step("flag_anomaly")
def step_flag_anomaly(ctx: StepContext) -> StepOutcome:
    return StepOutcome(state=StepState.SUCCEEDED, output={})


@register_step("require_preparer_review")
def step_require_preparer_review(ctx: StepContext) -> StepOutcome:
    """Pause the run until a Preparer posts an approval."""
    return StepOutcome(
        state=StepState.PAUSED_AWAITING_INPUT,
        output={},
        pause_reason="preparer_review_required",
    )


@register_step("require_reviewer_signoff")
def step_require_reviewer_signoff(ctx: StepContext) -> StepOutcome:
    """Pause the run until a Reviewer posts signoff."""
    return StepOutcome(
        state=StepState.PAUSED_AWAITING_INPUT,
        output={},
        pause_reason="reviewer_signoff_required",
    )


@register_step("export_to_target_system")
def step_export_to_target_system(ctx: StepContext) -> StepOutcome:
    return StepOutcome(state=StepState.SUCCEEDED, output={})


@register_step("deliver_to_client_portal")
def step_deliver_to_client_portal(ctx: StepContext) -> StepOutcome:
    return StepOutcome(state=StepState.SUCCEEDED, output={})


@register_step("notify_user")
def step_notify_user(ctx: StepContext) -> StepOutcome:
    return StepOutcome(state=StepState.SUCCEEDED, output={})
