"""Workflow orchestrator.

Responsibilities:
- ``start_run(template_id, engagement_id)`` creates a workflow_run row,
  pre-creates workflow_step_run rows in order, emits
  ``workflow.run_started`` audit.
- ``advance_run(run_id)`` executes the next pending step inside the
  registered executor's lifecycle.
- ``resume_run(run_id, resume_event)`` transitions a paused run back to
  running after a human event (preparer approval or reviewer signoff).
- State transitions are validated via ``state.can_transition_*``; any
  illegal transition raises ``InvalidTransition`` rather than silently
  corrupting run state.

Engine is synchronous + pure-Python. Wrapping a ``run_next_step`` call
in a Celery task is a trivial future step.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from accounting_parser.auth.audit import emit_audit_event
from accounting_parser.workflow.registry import StepContext, get_step
from accounting_parser.workflow.state import (
    InvalidTransition,
    RunState,
    StepOutcome,
    StepState,
    can_transition_run,
    can_transition_step,
)
from accounting_parser.workflow.templates import get_template

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types for UI + tests
# ---------------------------------------------------------------------------


@dataclass
class AdvanceResult:
    """What happened this tick of the engine."""

    run_id: UUID
    run_state: RunState
    step_name: str | None
    step_state: StepState | None
    step_output: dict[str, Any]
    pause_reason: str | None


# ---------------------------------------------------------------------------
# Engine API
# ---------------------------------------------------------------------------


def start_run(
    session: Session,
    *,
    tenant_id: UUID,
    engagement_id: UUID,
    template_id: str,
    actor_user_id: UUID | None = None,
) -> UUID:
    """Create a new workflow_run + pre-create workflow_step_run rows."""
    template = get_template(template_id)
    run_id = uuid4()

    session.execute(
        text(
            """
            INSERT INTO workflow_run (
                id, tenant_id, engagement_id, workflow_template_id, state
            )
            VALUES (:id, :tid, :eid, :tpl, :state)
            """
        ),
        {
            "id": str(run_id),
            "tid": str(tenant_id),
            "eid": str(engagement_id),
            "tpl": template_id,
            "state": RunState.PENDING.value,
        },
    )

    for idx, step in enumerate(template.steps):
        session.execute(
            text(
                """
                INSERT INTO workflow_step_run (
                    id, tenant_id, workflow_run_id, step_name, state,
                    input_payload
                )
                VALUES (:id, :tid, :rid, :name, :state, CAST(:cfg AS jsonb))
                """
            ),
            {
                "id": str(uuid4()),
                "tid": str(tenant_id),
                "rid": str(run_id),
                "name": f"{idx:02d}_{step.name}",
                "state": StepState.PENDING.value,
                "cfg": json.dumps({"step_type": step.step_type, **step.config}),
            },
        )

    emit_audit_event(
        session,
        action="workflow.run_started",
        tenant_id=tenant_id,
        resource_type="workflow_run",
        resource_id=run_id,
        actor_user_id=actor_user_id,
        payload={"template_id": template_id, "engagement_id": str(engagement_id)},
    )
    return run_id


def advance_run(
    session: Session,
    *,
    run_id: UUID,
    actor_user_id: UUID | None = None,
) -> AdvanceResult:
    """Execute the next PENDING step in the run.

    Transitions:
    - PENDING run + first PENDING step → RUNNING run + step.run_executor
    - RUNNING run + PENDING step → run step
    - Step returns SUCCEEDED → next step (or COMPLETED if no more)
    - Step returns FAILED → run FAILED; halt remaining steps
    - Step returns PAUSED_AWAITING_INPUT → run PAUSED_AWAITING_INPUT
    """
    run_row = _load_run(session, run_id)
    run_state = RunState(run_row["state"])

    if run_state in (RunState.COMPLETED, RunState.FAILED):
        return AdvanceResult(
            run_id=run_id, run_state=run_state, step_name=None,
            step_state=None, step_output={}, pause_reason=None,
        )
    if run_state == RunState.PAUSED_AWAITING_INPUT:
        raise InvalidTransition(
            f"Run {run_id} is paused; call resume_run before advancing."
        )

    # Bring run into RUNNING if we're starting.
    if run_state == RunState.PENDING:
        _transition_run(session, run_id, RunState.PENDING, RunState.RUNNING)

    next_step = _next_pending_step(session, run_id)
    if next_step is None:
        _transition_run(session, run_id, RunState.RUNNING, RunState.COMPLETED)
        _update_run_ended(session, run_id)
        emit_audit_event(
            session,
            action="workflow.run_completed",
            tenant_id=UUID(str(run_row["tenant_id"])),
            resource_type="workflow_run",
            resource_id=run_id,
            actor_user_id=actor_user_id,
            payload={},
        )
        return AdvanceResult(
            run_id=run_id, run_state=RunState.COMPLETED,
            step_name=None, step_state=None, step_output={}, pause_reason=None,
        )

    step_id = UUID(str(next_step["id"]))
    step_config = dict(next_step["input_payload"] or {})
    step_type = step_config.pop("step_type")
    _transition_step(session, step_id, StepState.PENDING, StepState.RUNNING)

    ctx = StepContext(
        session=session,
        tenant_id=UUID(str(run_row["tenant_id"])),
        engagement_id=UUID(str(run_row["engagement_id"])),
        workflow_run_id=run_id,
        step_name=next_step["step_name"],
        step_config=step_config,
        previous_outputs=_collect_previous_outputs(session, run_id),
    )
    try:
        outcome: StepOutcome = get_step(step_type)(ctx)
    except Exception as e:
        logger.exception("Step executor raised")
        outcome = StepOutcome(
            state=StepState.FAILED,
            output={"error": str(e), "exception_type": type(e).__name__},
        )

    session.execute(
        text(
            """
            UPDATE workflow_step_run
            SET state = :state,
                output_payload = CAST(:out AS jsonb),
                ended_at = now()
            WHERE id = :id
            """
        ),
        {
            "state": outcome.state.value,
            "out": json.dumps(outcome.output),
            "id": str(step_id),
        },
    )

    # Respond at the run level.
    if outcome.state == StepState.FAILED:
        _transition_run(session, run_id, RunState.RUNNING, RunState.FAILED)
        _update_run_ended(session, run_id, error_payload=outcome.output)
        emit_audit_event(
            session,
            action="workflow.run_failed",
            tenant_id=ctx.tenant_id,
            resource_type="workflow_run",
            resource_id=run_id,
            actor_user_id=actor_user_id,
            payload={"step_name": next_step["step_name"], "output": outcome.output},
        )
        return AdvanceResult(
            run_id=run_id, run_state=RunState.FAILED,
            step_name=next_step["step_name"], step_state=outcome.state,
            step_output=outcome.output, pause_reason=None,
        )

    if outcome.state == StepState.PAUSED_AWAITING_INPUT:
        _transition_run(session, run_id, RunState.RUNNING, RunState.PAUSED_AWAITING_INPUT)
        emit_audit_event(
            session,
            action="workflow.run_paused",
            tenant_id=ctx.tenant_id,
            resource_type="workflow_run",
            resource_id=run_id,
            actor_user_id=actor_user_id,
            payload={"step_name": next_step["step_name"], "reason": outcome.pause_reason},
        )
        return AdvanceResult(
            run_id=run_id, run_state=RunState.PAUSED_AWAITING_INPUT,
            step_name=next_step["step_name"], step_state=outcome.state,
            step_output=outcome.output, pause_reason=outcome.pause_reason,
        )

    # SUCCEEDED — stay in RUNNING for the next advance().
    return AdvanceResult(
        run_id=run_id, run_state=RunState.RUNNING,
        step_name=next_step["step_name"], step_state=outcome.state,
        step_output=outcome.output, pause_reason=None,
    )


def resume_run(
    session: Session,
    *,
    run_id: UUID,
    actor_user_id: UUID | None = None,
    resume_payload: dict[str, Any] | None = None,
) -> AdvanceResult:
    """Resume a paused run.

    Marks the currently-paused step as SUCCEEDED (the human event arrived)
    and transitions the run back to RUNNING. Call ``advance_run`` next to
    execute the following step.
    """
    run_row = _load_run(session, run_id)
    if RunState(run_row["state"]) != RunState.PAUSED_AWAITING_INPUT:
        raise InvalidTransition(f"Run {run_id} is not paused.")

    paused_step = session.execute(
        text(
            """
            SELECT id, step_name FROM workflow_step_run
            WHERE workflow_run_id = :rid
              AND state = :st
            LIMIT 1
            """
        ),
        {"rid": str(run_id), "st": StepState.PAUSED_AWAITING_INPUT.value},
    ).mappings().first()
    if paused_step is None:
        raise InvalidTransition(
            f"Run {run_id} is paused but no step is in paused_awaiting_input."
        )

    step_id = UUID(str(paused_step["id"]))
    _transition_step(session, step_id, StepState.PAUSED_AWAITING_INPUT, StepState.SUCCEEDED)
    session.execute(
        text(
            """
            UPDATE workflow_step_run
            SET output_payload = CAST(:out AS jsonb),
                ended_at = now()
            WHERE id = :id
            """
        ),
        {
            "out": json.dumps({"resumed": True, **(resume_payload or {})}),
            "id": str(step_id),
        },
    )
    _transition_run(
        session, run_id, RunState.PAUSED_AWAITING_INPUT, RunState.RUNNING
    )
    emit_audit_event(
        session,
        action="workflow.run_resumed",
        tenant_id=UUID(str(run_row["tenant_id"])),
        resource_type="workflow_run",
        resource_id=run_id,
        actor_user_id=actor_user_id,
        payload={"step_name": paused_step["step_name"], "payload": resume_payload or {}},
    )
    return AdvanceResult(
        run_id=run_id, run_state=RunState.RUNNING,
        step_name=paused_step["step_name"], step_state=StepState.SUCCEEDED,
        step_output={"resumed": True}, pause_reason=None,
    )


def drive_until_pause_or_done(
    session: Session,
    *,
    run_id: UUID,
    actor_user_id: UUID | None = None,
    max_iterations: int = 100,
) -> AdvanceResult:
    """Convenience: repeatedly advance until the run pauses, fails, or completes."""
    for _ in range(max_iterations):
        result = advance_run(session, run_id=run_id, actor_user_id=actor_user_id)
        if result.run_state in (RunState.COMPLETED, RunState.FAILED, RunState.PAUSED_AWAITING_INPUT):
            return result
    raise RuntimeError(
        f"drive_until_pause_or_done exceeded {max_iterations} iterations on run {run_id}"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_run(session: Session, run_id: UUID) -> dict[str, Any]:
    row = session.execute(
        text(
            """
            SELECT tenant_id, engagement_id, workflow_template_id, state,
                   started_at, ended_at
            FROM workflow_run WHERE id = :id
            """
        ),
        {"id": str(run_id)},
    ).mappings().first()
    if row is None:
        raise KeyError(f"workflow_run {run_id} not found")
    return dict(row)


def _next_pending_step(session: Session, run_id: UUID) -> dict[str, Any] | None:
    row = session.execute(
        text(
            """
            SELECT id, step_name, input_payload
            FROM workflow_step_run
            WHERE workflow_run_id = :rid
              AND state = 'pending'
            ORDER BY step_name
            LIMIT 1
            """
        ),
        {"rid": str(run_id)},
    ).mappings().first()
    return dict(row) if row else None


def _collect_previous_outputs(session: Session, run_id: UUID) -> dict[str, Any]:
    rows = session.execute(
        text(
            """
            SELECT step_name, output_payload
            FROM workflow_step_run
            WHERE workflow_run_id = :rid
              AND state = 'succeeded'
            """
        ),
        {"rid": str(run_id)},
    ).mappings().all()
    return {r["step_name"]: dict(r["output_payload"] or {}) for r in rows}


def _transition_run(
    session: Session, run_id: UUID, from_: RunState, to: RunState
) -> None:
    if not can_transition_run(from_, to):
        raise InvalidTransition(f"run {run_id}: {from_.value} → {to.value}")
    session.execute(
        text(
            """
            UPDATE workflow_run
            SET state = :to
            WHERE id = :id AND state = :from
            """
        ),
        {"id": str(run_id), "from": from_.value, "to": to.value},
    )


def _transition_step(
    session: Session, step_id: UUID, from_: StepState, to: StepState
) -> None:
    if not can_transition_step(from_, to):
        raise InvalidTransition(f"step {step_id}: {from_.value} → {to.value}")
    session.execute(
        text(
            """
            UPDATE workflow_step_run
            SET state = :to
            WHERE id = :id AND state = :from
            """
        ),
        {"id": str(step_id), "from": from_.value, "to": to.value},
    )


def _update_run_ended(
    session: Session, run_id: UUID, error_payload: dict[str, Any] | None = None
) -> None:
    session.execute(
        text(
            """
            UPDATE workflow_run
            SET ended_at = now(),
                error_payload = CAST(:err AS jsonb)
            WHERE id = :id
            """
        ),
        {
            "id": str(run_id),
            "err": json.dumps(error_payload) if error_payload else None,
        },
    )
