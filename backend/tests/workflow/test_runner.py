"""WorkflowRunner direct tests (no HTTP)."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from accounting_parser.workflow.registry import StepContext, StepRegistry, StepResult, StepStatus
from accounting_parser.workflow.runner import (
    ResumeNotAllowedError,
    TemplateNotFoundError,
    WorkflowRunner,
)
from accounting_parser.workflow.state import WorkflowState
from accounting_parser.workflow.templates import (
    WorkflowStepDef,
    WorkflowTemplate,
    register_template,
)
from tests.workflow.conftest import SeededEngagement


@pytest.fixture
def platform_session(superuser_engine: Engine):
    factory = sessionmaker(bind=superuser_engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()


def test_monthly_close_walks_to_preparer_pause(
    platform_session: Session,
    workflow_registry: StepRegistry,
    seeded_engagement: SeededEngagement,
):
    """Start monthly_close → pause at require_preparer_review."""
    runner = WorkflowRunner(registry=workflow_registry)
    run = runner.start(
        platform_session,
        tenant_id=seeded_engagement.tenant_id,
        engagement_id=seeded_engagement.engagement_id,
        template_id="monthly_close_bookkeeping",
        started_by_user_id=seeded_engagement.preparer_id,
    )
    platform_session.commit()

    assert run.state is WorkflowState.PAUSED_AWAITING_INPUT
    assert run.pause_reason["required_role"] == "preparer"
    # Parse, classify, validate completed before the pause.
    assert run.current_step_index == 3
    assert "parse_source_docs" in run.context
    assert "classify_accounts" in run.context
    assert "validate_tb" in run.context


def test_resume_with_preparer_role_advances_to_completion(
    platform_session: Session,
    workflow_registry: StepRegistry,
    seeded_engagement: SeededEngagement,
):
    """Preparer resume → remaining steps run → COMPLETED."""
    runner = WorkflowRunner(registry=workflow_registry)
    run = runner.start(
        platform_session,
        tenant_id=seeded_engagement.tenant_id,
        engagement_id=seeded_engagement.engagement_id,
        template_id="monthly_close_bookkeeping",
        started_by_user_id=seeded_engagement.preparer_id,
    )
    platform_session.commit()

    resumed = runner.resume(
        platform_session,
        run_id=run.id,
        actor_user_id=seeded_engagement.preparer_id,
        actor_role="preparer",
    )
    platform_session.commit()
    assert resumed.state is WorkflowState.COMPLETED
    # post_adjustments + emit_cch_export recorded in context.
    assert "post_adjustments" in resumed.context
    assert "emit_cch_export" in resumed.context


def test_resume_with_wrong_role_refused(
    platform_session: Session,
    workflow_registry: StepRegistry,
    seeded_engagement: SeededEngagement,
):
    runner = WorkflowRunner(registry=workflow_registry)
    run = runner.start(
        platform_session,
        tenant_id=seeded_engagement.tenant_id,
        engagement_id=seeded_engagement.engagement_id,
        template_id="monthly_close_bookkeeping",
        started_by_user_id=seeded_engagement.preparer_id,
    )
    platform_session.commit()

    with pytest.raises(ResumeNotAllowedError):
        runner.resume(
            platform_session,
            run_id=run.id,
            actor_user_id=seeded_engagement.reviewer_id,
            actor_role="reviewer",  # pause required 'preparer'
        )


def test_resume_on_running_run_refused(
    platform_session: Session,
    workflow_registry: StepRegistry,
    seeded_engagement: SeededEngagement,
):
    """Cannot resume a run that isn't paused."""
    runner = WorkflowRunner(registry=workflow_registry)
    # Build a template with no pause step to get a quickly-completing
    # run that we then try to resume.
    template = WorkflowTemplate(
        id="no_pause_test",
        title="No Pause",
        steps=(WorkflowStepDef(name="only_step", step_type="parse"),),
    )
    register_template(template)
    run = runner.start(
        platform_session,
        tenant_id=seeded_engagement.tenant_id,
        engagement_id=seeded_engagement.engagement_id,
        template_id="no_pause_test",
        started_by_user_id=seeded_engagement.preparer_id,
    )
    platform_session.commit()
    assert run.state is WorkflowState.COMPLETED

    with pytest.raises(ResumeNotAllowedError):
        runner.resume(
            platform_session,
            run_id=run.id,
            actor_user_id=seeded_engagement.preparer_id,
            actor_role="preparer",
        )


def test_unknown_template_raises(
    platform_session: Session,
    workflow_registry: StepRegistry,
    seeded_engagement: SeededEngagement,
):
    runner = WorkflowRunner(registry=workflow_registry)
    with pytest.raises(TemplateNotFoundError):
        runner.start(
            platform_session,
            tenant_id=seeded_engagement.tenant_id,
            engagement_id=seeded_engagement.engagement_id,
            template_id="nonexistent",
            started_by_user_id=seeded_engagement.preparer_id,
        )


def test_step_failure_halts_and_marks_failed(
    platform_session: Session,
    seeded_engagement: SeededEngagement,
):
    """A failing step raises workflow to FAILED; subsequent steps do NOT run."""

    def boom(ctx: StepContext) -> StepResult:
        return StepResult(status=StepStatus.FAILED, error="validator broke")

    def ok(ctx: StepContext) -> StepResult:
        return StepResult(status=StepStatus.COMPLETED)

    reg = StepRegistry()
    reg.register("parse", ok)
    reg.register("classify", ok)
    reg.register("validate", boom)
    # subsequent step types registered but they must NOT run
    reg.register("require_preparer_review", ok)
    reg.register("post_adjustments", ok)
    reg.register("emit_export", ok)

    runner = WorkflowRunner(registry=reg)
    run = runner.start(
        platform_session,
        tenant_id=seeded_engagement.tenant_id,
        engagement_id=seeded_engagement.engagement_id,
        template_id="monthly_close_bookkeeping",
        started_by_user_id=seeded_engagement.preparer_id,
    )
    platform_session.commit()

    assert run.state is WorkflowState.FAILED
    assert "validator broke" in (run.error or "")
    # Only 3 step_runs exist (parse, classify, validate).
    count = platform_session.execute(
        text("SELECT count(*) FROM workflow_step_run WHERE run_id = :rid"),
        {"rid": str(run.id)},
    ).scalar_one()
    assert count == 3


def test_handler_exception_is_caught_and_marks_failed(
    platform_session: Session,
    seeded_engagement: SeededEngagement,
):
    def raise_runtime(ctx: StepContext) -> StepResult:
        raise RuntimeError("surprise")

    reg = StepRegistry()
    reg.register("parse", raise_runtime)
    for t in (
        "classify",
        "validate",
        "require_preparer_review",
        "post_adjustments",
        "emit_export",
    ):
        reg.register(t, lambda ctx: StepResult(status=StepStatus.COMPLETED))

    runner = WorkflowRunner(registry=reg)
    run = runner.start(
        platform_session,
        tenant_id=seeded_engagement.tenant_id,
        engagement_id=seeded_engagement.engagement_id,
        template_id="monthly_close_bookkeeping",
        started_by_user_id=seeded_engagement.preparer_id,
    )
    platform_session.commit()
    assert run.state is WorkflowState.FAILED
    assert "RuntimeError" in (run.error or "")


def test_audit_events_cover_lifecycle(
    platform_session: Session,
    workflow_registry: StepRegistry,
    seeded_engagement: SeededEngagement,
):
    """started → paused → resumed → completed all emit audit rows."""
    runner = WorkflowRunner(registry=workflow_registry)
    run = runner.start(
        platform_session,
        tenant_id=seeded_engagement.tenant_id,
        engagement_id=seeded_engagement.engagement_id,
        template_id="monthly_close_bookkeeping",
        started_by_user_id=seeded_engagement.preparer_id,
    )
    platform_session.commit()
    runner.resume(
        platform_session,
        run_id=run.id,
        actor_user_id=seeded_engagement.preparer_id,
        actor_role="preparer",
    )
    platform_session.commit()
    actions = set(
        platform_session.execute(
            text(
                """
                SELECT action FROM audit_log_entry
                WHERE resource_id = :rid
                """
            ),
            {"rid": str(run.id)},
        ).scalars()
    )
    assert {
        "workflow.started",
        "workflow.paused",
        "workflow.resumed",
        "workflow.completed",
    }.issubset(actions)
