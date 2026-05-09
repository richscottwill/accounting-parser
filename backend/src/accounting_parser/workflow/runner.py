"""WorkflowRunner — executes a workflow against persistent state.

The runner is the sole entry point for state-changing operations on
a workflow run:

- ``start(template_id, engagement_id)`` — create a ``workflow_run``
  row in PENDING, audit ``workflow.started``, and advance.
- ``advance(run_id)`` — execute the next step. Transitions:
  PENDING → RUNNING → { RUNNING (continue), PAUSED_AWAITING_INPUT,
  COMPLETED, FAILED }. Idempotent when called on a run already in
  a terminal state.
- ``resume(run_id, actor_user_id, role)`` — resume from
  PAUSED_AWAITING_INPUT iff the provided role matches the pause
  reason's ``required_role``. Audits ``workflow.resumed``. Then calls
  advance() to kick the next step.

The runner is called synchronously in P1.4. Celery integration (the
"real" async orchestration) wraps these calls in tasks without
changing the core contract.

### Why synchronous at P1.4

Celery adds a moving part (broker, worker lifecycle, retry
semantics) that isn't needed to prove orchestration correctness.
The state machine, pause semantics, and audit chain are all
testable against the synchronous runner. Wrapping in Celery is a
few dozen lines that translates
``runner.advance(run_id)`` into ``advance_task.delay(run_id)``;
preserves the runner as the source of truth for behavior.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from accounting_parser.auth.audit import append_auth_event
from accounting_parser.workflow.registry import StepContext, StepRegistry, StepResult, StepStatus
from accounting_parser.workflow.state import WorkflowRun, WorkflowState
from accounting_parser.workflow.templates import WorkflowTemplate, get_template


class WorkflowError(RuntimeError):
    """Base class for runner-level failures."""


class TemplateNotFoundError(WorkflowError):
    pass


class ResumeNotAllowedError(WorkflowError):
    """Raised when a resume attempt fails role-matching or state check."""


@dataclass(frozen=True)
class WorkflowRunView:
    """Serializable projection of a run for HTTP responses."""

    run_id: str
    template_id: str
    engagement_id: str
    state: str
    current_step_index: int
    pause_reason: dict
    context: dict
    error: str | None


class WorkflowRunner:
    """Synchronous state-machine driver."""

    def __init__(self, *, registry: StepRegistry) -> None:
        self.registry = registry

    # ---- Start ---------------------------------------------------

    def start(
        self,
        session: Session,
        *,
        tenant_id: UUID,
        engagement_id: UUID,
        template_id: str,
        started_by_user_id: UUID,
    ) -> WorkflowRun:
        """Create a new workflow run for an engagement and advance once."""
        try:
            template = get_template(template_id)
        except KeyError as e:
            raise TemplateNotFoundError(f"unknown template {template_id!r}") from e

        run_id = uuid4()
        now = datetime.now(UTC)
        session.execute(
            text(
                """
                INSERT INTO workflow_run (
                    id, tenant_id, engagement_id, template_id, state,
                    current_step_index, pause_reason, context,
                    created_at, updated_at
                ) VALUES (
                    :id, :tid, :eid, :tpl, 'pending',
                    0, '{}'::jsonb, '{}'::jsonb,
                    :now, :now
                )
                """
            ),
            {
                "id": str(run_id),
                "tid": str(tenant_id),
                "eid": str(engagement_id),
                "tpl": template.id,
                "now": now,
            },
        )
        append_auth_event(
            session,
            tenant_id=tenant_id,
            actor_user_id=started_by_user_id,
            action="workflow.started",
            resource_id=run_id,
            payload={
                "template_id": template.id,
                "engagement_id": str(engagement_id),
            },
        )
        # Drive the first step immediately so the run doesn't idle
        # in 'pending' waiting for a second API call.
        return self.advance(
            session, run_id=run_id, template=template, actor_user_id=started_by_user_id
        )

    # ---- Advance -------------------------------------------------

    def advance(
        self,
        session: Session,
        *,
        run_id: UUID,
        template: WorkflowTemplate | None = None,
        actor_user_id: UUID | None = None,
    ) -> WorkflowRun:
        """Execute steps until the run pauses, completes, or fails.

        Loops so a sequence of non-pausing compute steps executes
        in one call; stops at the first pause / terminal state.
        Each step's outcome is persisted BEFORE the next step runs,
        so a crash between steps leaves a recoverable state.
        """
        run = self._load_run(session, run_id)
        if run.state.is_terminal:
            return run
        if template is None:
            template = get_template(run.template_id)

        # Mark running if we were pending.
        if run.state is WorkflowState.PENDING:
            self._set_state(session, run, WorkflowState.RUNNING)

        while run.state is WorkflowState.RUNNING:
            if run.current_step_index >= len(template.steps):
                self._set_state(session, run, WorkflowState.COMPLETED)
                append_auth_event(
                    session,
                    tenant_id=run.tenant_id,
                    actor_user_id=actor_user_id,
                    action="workflow.completed",
                    resource_id=run.id,
                    payload={"template_id": run.template_id},
                )
                break

            step_def = template.steps[run.current_step_index]
            handler = self.registry.get(step_def.step_type)

            ctx = StepContext(
                tenant_id=run.tenant_id,
                engagement_id=run.engagement_id,
                run_id=run.id,
                step_name=step_def.name,
                step_type=step_def.step_type,
                step_config=dict(step_def.config),
                run_context=dict(run.context),
            )

            step_run_id = uuid4()
            started_at = datetime.now(UTC)
            self._insert_step_run(
                session,
                step_run_id=step_run_id,
                run=run,
                step_def=step_def,
                started_at=started_at,
            )

            try:
                result: StepResult = handler(ctx)
            except Exception as e:  # noqa: BLE001
                # Treat any handler exception as step failure.
                self._complete_step_run(
                    session,
                    step_run_id=step_run_id,
                    state="failed",
                    error=f"{type(e).__name__}: {e}",
                    payload={},
                )
                run.error = f"{step_def.name}: {type(e).__name__}: {e}"
                self._set_state(session, run, WorkflowState.FAILED)
                append_auth_event(
                    session,
                    tenant_id=run.tenant_id,
                    actor_user_id=actor_user_id,
                    action="workflow.failed",
                    resource_id=run.id,
                    payload={
                        "step_name": step_def.name,
                        "error": run.error,
                    },
                )
                break

            if result.status is StepStatus.COMPLETED:
                # Persist step run + merge output into context.
                self._complete_step_run(
                    session,
                    step_run_id=step_run_id,
                    state="completed",
                    payload=result.output,
                )
                run.context[step_def.name] = result.output
                run.current_step_index += 1
                self._persist_run_progress(session, run)
                continue

            if result.status is StepStatus.PAUSED:
                self._complete_step_run(
                    session,
                    step_run_id=step_run_id,
                    state="paused",
                    payload=result.pause_reason,
                )
                run.pause_reason = dict(result.pause_reason)
                self._set_state(session, run, WorkflowState.PAUSED_AWAITING_INPUT)
                append_auth_event(
                    session,
                    tenant_id=run.tenant_id,
                    actor_user_id=actor_user_id,
                    action="workflow.paused",
                    resource_id=run.id,
                    payload={
                        "step_name": step_def.name,
                        "required_role": result.pause_reason.get("required_role"),
                    },
                )
                break

            # StepStatus.FAILED path.
            self._complete_step_run(
                session,
                step_run_id=step_run_id,
                state="failed",
                error=result.error,
                payload={},
            )
            run.error = result.error
            self._set_state(session, run, WorkflowState.FAILED)
            append_auth_event(
                session,
                tenant_id=run.tenant_id,
                actor_user_id=actor_user_id,
                action="workflow.failed",
                resource_id=run.id,
                payload={"step_name": step_def.name, "error": run.error},
            )
            break

        return run

    # ---- Resume --------------------------------------------------

    def resume(
        self,
        session: Session,
        *,
        run_id: UUID,
        actor_user_id: UUID,
        actor_role: str,
    ) -> WorkflowRun:
        """Resume a paused run; role must match the pause reason's
        ``required_role``.
        """
        run = self._load_run(session, run_id)
        if run.state is not WorkflowState.PAUSED_AWAITING_INPUT:
            raise ResumeNotAllowedError(f"run is in state {run.state.value}; cannot resume")
        required = run.pause_reason.get("required_role")
        if required and actor_role != required:
            raise ResumeNotAllowedError(
                f"resume requires role {required!r}; actor has {actor_role!r}"
            )
        # Advance past the pause step.
        run.pause_reason = {}
        run.current_step_index += 1
        self._set_state(session, run, WorkflowState.RUNNING)
        self._persist_run_progress(session, run)
        append_auth_event(
            session,
            tenant_id=run.tenant_id,
            actor_user_id=actor_user_id,
            action="workflow.resumed",
            resource_id=run.id,
            payload={"resumed_by_role": actor_role},
        )
        return self.advance(session, run_id=run.id, actor_user_id=actor_user_id)

    # ---- View ----------------------------------------------------

    def get_view(self, session: Session, *, run_id: UUID) -> WorkflowRunView:
        run = self._load_run(session, run_id)
        return WorkflowRunView(
            run_id=str(run.id),
            template_id=run.template_id,
            engagement_id=str(run.engagement_id),
            state=run.state.value,
            current_step_index=run.current_step_index,
            pause_reason=run.pause_reason,
            context=run.context,
            error=run.error,
        )

    # ---- Persistence helpers ------------------------------------

    def _load_run(self, session: Session, run_id: UUID) -> WorkflowRun:
        row = session.execute(
            text(
                """
                SELECT id, tenant_id, engagement_id, template_id, state,
                       current_step_index, pause_reason, context,
                       created_at, updated_at, error
                FROM workflow_run WHERE id = :id
                """
            ),
            {"id": str(run_id)},
        ).first()
        if row is None:
            raise WorkflowError(f"workflow_run {run_id} not found")
        pause_reason = row[6] if isinstance(row[6], dict) else json.loads(row[6] or "{}")
        context = row[7] if isinstance(row[7], dict) else json.loads(row[7] or "{}")
        return WorkflowRun(
            id=UUID(str(row[0])),
            tenant_id=UUID(str(row[1])),
            engagement_id=UUID(str(row[2])),
            template_id=str(row[3]),
            state=WorkflowState(str(row[4])),
            current_step_index=int(row[5]),
            pause_reason=pause_reason,
            context=context,
            created_at=row[8],
            updated_at=row[9],
            error=row[10],
        )

    def _set_state(self, session: Session, run: WorkflowRun, new_state: WorkflowState) -> None:
        run.state = new_state
        now = datetime.now(UTC)
        session.execute(
            text(
                """
                UPDATE workflow_run
                SET state = :st, updated_at = :now,
                    pause_reason = CAST(:pause AS jsonb),
                    error = :err
                WHERE id = :id
                """
            ),
            {
                "id": str(run.id),
                "st": new_state.value,
                "now": now,
                "pause": json.dumps(run.pause_reason),
                "err": run.error,
            },
        )

    def _persist_run_progress(self, session: Session, run: WorkflowRun) -> None:
        now = datetime.now(UTC)
        session.execute(
            text(
                """
                UPDATE workflow_run
                SET current_step_index = :idx,
                    context = CAST(:ctx AS jsonb),
                    pause_reason = CAST(:pause AS jsonb),
                    state = :st,
                    updated_at = :now
                WHERE id = :id
                """
            ),
            {
                "id": str(run.id),
                "idx": run.current_step_index,
                "ctx": json.dumps(run.context),
                "pause": json.dumps(run.pause_reason),
                "st": run.state.value,
                "now": now,
            },
        )

    def _insert_step_run(
        self,
        session: Session,
        *,
        step_run_id: UUID,
        run: WorkflowRun,
        step_def,
        started_at: datetime,
    ) -> None:
        session.execute(
            text(
                """
                INSERT INTO workflow_step_run (
                    id, tenant_id, run_id, step_index, step_name,
                    step_type, state, started_at, attempt, payload
                ) VALUES (
                    :id, :tid, :rid, :idx, :name,
                    :typ, 'running', :started, 1, '{}'::jsonb
                )
                """
            ),
            {
                "id": str(step_run_id),
                "tid": str(run.tenant_id),
                "rid": str(run.id),
                "idx": run.current_step_index,
                "name": step_def.name,
                "typ": step_def.step_type,
                "started": started_at,
            },
        )

    def _complete_step_run(
        self,
        session: Session,
        *,
        step_run_id: UUID,
        state: str,
        payload: dict,
        error: str | None = None,
    ) -> None:
        session.execute(
            text(
                """
                UPDATE workflow_step_run
                SET state = :st,
                    ended_at = :now,
                    payload = CAST(:pl AS jsonb),
                    error = :err
                WHERE id = :id
                """
            ),
            {
                "id": str(step_run_id),
                "st": state,
                "now": datetime.now(UTC),
                "pl": json.dumps(payload),
                "err": error,
            },
        )
