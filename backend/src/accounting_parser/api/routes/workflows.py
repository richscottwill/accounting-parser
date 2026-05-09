"""Workflow HTTP routes.

- ``POST /engagements/{id}/workflows`` — start a run from a template.
- ``GET  /workflows/{run_id}`` — read current state.
- ``GET  /engagements/{id}/workflows`` — list runs for an engagement.
- ``POST /workflows/{run_id}/resume`` — resume a paused run.
  Requires a role matching the pause reason's ``required_role``.
- ``GET  /workflows/{run_id}/steps`` — list step attempts.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from accounting_parser.api.deps import get_current_user, get_db
from accounting_parser.auth.adapter import AuthenticatedUser
from accounting_parser.workflow.registry import StepRegistry
from accounting_parser.workflow.runner import (
    ResumeNotAllowedError,
    TemplateNotFoundError,
    WorkflowRunner,
)

router = APIRouter()


class StartRunBody(BaseModel):
    template_id: str


class RunResponse(BaseModel):
    run_id: str
    template_id: str
    engagement_id: str
    state: str
    current_step_index: int
    pause_reason: dict
    context: dict
    error: str | None = None


class RunListResponse(BaseModel):
    engagement_id: str
    runs: list[RunResponse]


class StepRunResponse(BaseModel):
    id: str
    step_index: int
    step_name: str
    step_type: str
    state: str
    started_at: str
    ended_at: str | None
    attempt: int
    payload: dict
    error: str | None


class StepListResponse(BaseModel):
    run_id: str
    steps: list[StepRunResponse]


class ResumeBody(BaseModel):
    # Role the caller claims — validated against the pause reason
    # and the caller's ``app_user.role`` by the service.
    role: str


def _runner(request: Request) -> WorkflowRunner:
    registry: StepRegistry = request.app.state.workflow_registry
    return WorkflowRunner(registry=registry)


@router.post(
    "/engagements/{engagement_id}/workflows",
    response_model=RunResponse,
    status_code=201,
)
async def start_workflow(
    engagement_id: UUID,
    body: StartRunBody,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> RunResponse:
    """Start a new workflow run for an engagement."""
    row = session.execute(
        text("SELECT 1 FROM engagement WHERE id = :eid AND tenant_id = :tid"),
        {"eid": str(engagement_id), "tid": str(user.tenant_id)},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Engagement not found")

    runner = _runner(request)
    try:
        run = runner.start(
            session,
            tenant_id=user.tenant_id,
            engagement_id=engagement_id,
            template_id=body.template_id,
            started_by_user_id=user.user_id,
        )
    except TemplateNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _view(runner.get_view(session, run_id=run.id))


@router.get("/workflows/{run_id}", response_model=RunResponse)
async def get_workflow_run(
    run_id: UUID,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> RunResponse:
    runner = _runner(request)
    try:
        view = runner.get_view(session, run_id=run_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="Workflow run not found") from e
    return _view(view)


@router.get("/engagements/{engagement_id}/workflows", response_model=RunListResponse)
async def list_workflow_runs(
    engagement_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> RunListResponse:
    rows = session.execute(
        text(
            """
            SELECT id, template_id, engagement_id, state,
                   current_step_index, pause_reason, context, error
            FROM workflow_run
            WHERE engagement_id = :eid AND tenant_id = :tid
            ORDER BY created_at DESC
            """
        ),
        {"eid": str(engagement_id), "tid": str(user.tenant_id)},
    ).all()
    import json

    def _jd(raw):
        return raw if isinstance(raw, dict) else json.loads(raw or "{}")

    runs = [
        RunResponse(
            run_id=str(r[0]),
            template_id=str(r[1]),
            engagement_id=str(r[2]),
            state=str(r[3]),
            current_step_index=int(r[4]),
            pause_reason=_jd(r[5]),
            context=_jd(r[6]),
            error=r[7],
        )
        for r in rows
    ]
    return RunListResponse(engagement_id=str(engagement_id), runs=runs)


@router.post("/workflows/{run_id}/resume", response_model=RunResponse)
async def resume_workflow(
    run_id: UUID,
    body: ResumeBody,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> RunResponse:
    """Resume a paused workflow run.

    The role supplied in the body MUST match both (a) the pause
    reason's required_role and (b) the caller's app_user.role.
    Mismatch returns 403.
    """
    if body.role != user.role.value:
        raise HTTPException(
            status_code=403,
            detail=f"caller has role {user.role.value!r}; cannot act as {body.role!r}",
        )
    runner = _runner(request)
    try:
        runner.resume(
            session,
            run_id=run_id,
            actor_user_id=user.user_id,
            actor_role=body.role,
        )
    except ResumeNotAllowedError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _view(runner.get_view(session, run_id=run_id))


@router.get("/workflows/{run_id}/steps", response_model=StepListResponse)
async def list_workflow_steps(
    run_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> StepListResponse:
    rows = session.execute(
        text(
            """
            SELECT id, step_index, step_name, step_type, state,
                   started_at, ended_at, attempt, payload, error
            FROM workflow_step_run
            WHERE run_id = :rid AND tenant_id = :tid
            ORDER BY started_at ASC
            """
        ),
        {"rid": str(run_id), "tid": str(user.tenant_id)},
    ).all()
    import json

    def _jd(raw):
        return raw if isinstance(raw, dict) else json.loads(raw or "{}")

    steps = [
        StepRunResponse(
            id=str(r[0]),
            step_index=int(r[1]),
            step_name=str(r[2]),
            step_type=str(r[3]),
            state=str(r[4]),
            started_at=r[5].isoformat(),
            ended_at=r[6].isoformat() if r[6] else None,
            attempt=int(r[7]),
            payload=_jd(r[8]),
            error=r[9],
        )
        for r in rows
    ]
    return StepListResponse(run_id=str(run_id), steps=steps)


def _view(view) -> RunResponse:
    return RunResponse(
        run_id=view.run_id,
        template_id=view.template_id,
        engagement_id=view.engagement_id,
        state=view.state,
        current_step_index=view.current_step_index,
        pause_reason=view.pause_reason,
        context=view.context,
        error=view.error,
    )
