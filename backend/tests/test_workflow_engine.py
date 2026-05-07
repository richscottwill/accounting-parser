"""Task 17 workflow engine tests.

Covers:
- Template registry — all 5 built-in templates present.
- Step registry — known step types match spec.
- start_run creates workflow_run + step rows in order.
- advance_run drives a happy path to COMPLETED.
- A step returning FAILED halts the run with error_payload recorded.
- A step returning PAUSED_AWAITING_INPUT pauses the run, then
  resume_run + advance_run completes it.
- Invalid state transitions raise InvalidTransition.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from accounting_parser.db.session import set_tenant_context
from accounting_parser.workflow.engine import (
    advance_run,
    drive_until_pause_or_done,
    resume_run,
    start_run,
)
from accounting_parser.workflow.registry import known_step_types
from accounting_parser.workflow.state import (
    InvalidTransition,
    RunState,
    StepState,
    can_transition_run,
    can_transition_step,
)
from accounting_parser.workflow.templates import get_template, list_templates


# ---------------------------------------------------------------------------
# Pure unit tests — no DB needed.
# ---------------------------------------------------------------------------

def test_all_five_built_in_templates_registered() -> None:
    ids = list_templates()
    for required in (
        "new_client_onboarding",
        "monthly_close_bookkeeping",
        "year_end_tax_prep",
        "engagement_review_and_deliver",
        "individual_1040_prep",
    ):
        assert required in ids


def test_year_end_tax_prep_has_signoff_gates() -> None:
    t = get_template("year_end_tax_prep")
    step_types = [s.step_type for s in t.steps]
    assert "require_preparer_review" in step_types
    assert "require_reviewer_signoff" in step_types


def test_known_step_types_cover_spec() -> None:
    types = set(known_step_types())
    for required in (
        "ingest", "parse", "classify", "validate",
        "propose_aje", "propose_rje", "propose_tje",
        "run_book_to_tax", "generate_lead_schedules",
        "run_cash_to_accrual", "compute_fixed_asset_depreciation",
        "reconcile_1099", "reconcile_payroll", "apply_apportionment",
        "rollforward_from_prior_year", "flag_anomaly",
        "require_preparer_review", "require_reviewer_signoff",
        "export_to_target_system", "deliver_to_client_portal",
        "notify_user",
    ):
        assert required in types, f"missing step type {required!r}"


def test_state_machine_allowed_transitions() -> None:
    assert can_transition_run(RunState.PENDING, RunState.RUNNING)
    assert can_transition_run(RunState.RUNNING, RunState.COMPLETED)
    assert not can_transition_run(RunState.COMPLETED, RunState.RUNNING)
    assert can_transition_step(StepState.RUNNING, StepState.SUCCEEDED)
    assert not can_transition_step(StepState.SUCCEEDED, StepState.RUNNING)


# ---------------------------------------------------------------------------
# Integration tests — hit Postgres.
# ---------------------------------------------------------------------------

@pytest.fixture
def seeded(migrated_engine: Engine) -> dict:
    tenant_id = uuid4()
    firm_id = uuid4()
    user_id = uuid4()
    client_id = uuid4()
    engagement_id = uuid4()
    nm = f"WF Co {tenant_id.hex[:8]}"

    with migrated_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO tenant (id, name, kms_key_alias) VALUES (:i, :n, :a)"),
            {"i": str(tenant_id), "n": nm, "a": f"alias/{tenant_id}"},
        )
        conn.execute(
            text("INSERT INTO firm (id, tenant_id, name) VALUES (:i, :t, :n)"),
            {"i": str(firm_id), "t": str(tenant_id), "n": nm},
        )
        conn.execute(
            text(
                """
                INSERT INTO app_user (
                    id, tenant_id, firm_id, cognito_sub, email, role, mfa_required
                ) VALUES (:i, :t, :f, :s, :e, 'firm_administrator', true)
                """
            ),
            {
                "i": str(user_id), "t": str(tenant_id), "f": str(firm_id),
                "s": f"sub-{user_id}", "e": f"u-{tenant_id.hex[:6]}@example.com",
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO client (
                    id, tenant_id, firm_id, name, entity_type, fiscal_year_end_month
                ) VALUES (:i, :t, :f, :n, 's_corporation', 12)
                """
            ),
            {"i": str(client_id), "t": str(tenant_id), "f": str(firm_id), "n": nm},
        )
        conn.execute(
            text(
                """
                INSERT INTO engagement (
                    id, tenant_id, client_id, name, engagement_type, tax_year, status
                ) VALUES (:i, :t, :c, '2025 return', 'tax_return', 2025, 'in_progress')
                """
            ),
            {"i": str(engagement_id), "t": str(tenant_id), "c": str(client_id)},
        )
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "engagement_id": engagement_id,
    }


@pytest.fixture
def app_session(app_engine: Engine, seeded: dict) -> Session:
    SessionLocal = sessionmaker(bind=app_engine, expire_on_commit=False)
    s = SessionLocal()
    set_tenant_context(s, seeded["tenant_id"])
    try:
        yield s
        s.commit()
    finally:
        s.close()


def test_start_run_creates_rows_in_order(seeded: dict, app_session: Session) -> None:
    run_id = start_run(
        app_session,
        tenant_id=seeded["tenant_id"],
        engagement_id=seeded["engagement_id"],
        template_id="engagement_review_and_deliver",
        actor_user_id=seeded["user_id"],
    )
    app_session.flush()

    rows = app_session.execute(
        text(
            """
            SELECT step_name, state FROM workflow_step_run
            WHERE workflow_run_id = :r ORDER BY step_name
            """
        ),
        {"r": str(run_id)},
    ).all()
    names = [r[0] for r in rows]
    assert names[0].startswith("00_")
    assert names[1].startswith("01_")
    assert names[2].startswith("02_")
    assert all(state == "pending" for _, state in rows)


def test_drive_until_completed_on_monthly_close_pauses_at_preparer_review(
    seeded: dict, app_session: Session
) -> None:
    # Add a Document so the ingest step succeeds.
    doc_id = uuid4()
    app_session.execute(
        text(
            """
            INSERT INTO document (
                id, tenant_id, client_id, engagement_id, filename,
                content_type, byte_size, sha256, s3_bucket, s3_key, ingest_state
            ) VALUES (:id, :t, :c, :e, 'tb.pdf', 'application/pdf',
                      10, :h, 'b', 'k', 'received')
            """
        ),
        {
            "id": str(doc_id),
            "t": str(seeded["tenant_id"]),
            "c": app_session.execute(
                text("SELECT client_id FROM engagement WHERE id = :e"),
                {"e": str(seeded["engagement_id"])},
            ).scalar(),
            "e": str(seeded["engagement_id"]),
            "h": b"x" * 32,
        },
    )

    run_id = start_run(
        app_session,
        tenant_id=seeded["tenant_id"],
        engagement_id=seeded["engagement_id"],
        template_id="monthly_close_bookkeeping",
        actor_user_id=seeded["user_id"],
    )
    result = drive_until_pause_or_done(app_session, run_id=run_id)
    assert result.run_state == RunState.PAUSED_AWAITING_INPUT
    assert result.pause_reason == "preparer_review_required"


def test_resume_and_complete_run(seeded: dict, app_session: Session) -> None:
    doc_id = uuid4()
    client_id = app_session.execute(
        text("SELECT client_id FROM engagement WHERE id = :e"),
        {"e": str(seeded["engagement_id"])},
    ).scalar()
    app_session.execute(
        text(
            """
            INSERT INTO document (
                id, tenant_id, client_id, engagement_id, filename,
                content_type, byte_size, sha256, s3_bucket, s3_key, ingest_state
            ) VALUES (:id, :t, :c, :e, 'x.pdf', 'application/pdf',
                      10, :h, 'b', 'k', 'received')
            """
        ),
        {
            "id": str(doc_id),
            "t": str(seeded["tenant_id"]),
            "c": client_id,
            "e": str(seeded["engagement_id"]),
            "h": b"y" * 32,
        },
    )

    run_id = start_run(
        app_session,
        tenant_id=seeded["tenant_id"],
        engagement_id=seeded["engagement_id"],
        template_id="monthly_close_bookkeeping",
        actor_user_id=seeded["user_id"],
    )
    drive_until_pause_or_done(app_session, run_id=run_id)

    resume_run(
        app_session, run_id=run_id, actor_user_id=seeded["user_id"],
        resume_payload={"approver_note": "ok"},
    )
    result = drive_until_pause_or_done(app_session, run_id=run_id)
    assert result.run_state == RunState.COMPLETED


def test_failed_step_halts_run(seeded: dict, app_session: Session) -> None:
    # Insert a minimal custom run that runs a single validate step with
    # fail_for_test=true.
    run_id = uuid4()
    app_session.execute(
        text(
            """
            INSERT INTO workflow_run (id, tenant_id, engagement_id,
                                       workflow_template_id, state)
            VALUES (:i, :t, :e, 'custom', 'pending')
            """
        ),
        {
            "i": str(run_id), "t": str(seeded["tenant_id"]),
            "e": str(seeded["engagement_id"]),
        },
    )
    step_id = uuid4()
    import json

    app_session.execute(
        text(
            """
            INSERT INTO workflow_step_run (
                id, tenant_id, workflow_run_id, step_name, state, input_payload
            )
            VALUES (:i, :t, :r, '00_validate', 'pending',
                    CAST(:cfg AS jsonb))
            """
        ),
        {
            "i": str(step_id),
            "t": str(seeded["tenant_id"]),
            "r": str(run_id),
            "cfg": json.dumps({"step_type": "validate", "fail_for_test": True}),
        },
    )

    result = drive_until_pause_or_done(app_session, run_id=run_id)
    assert result.run_state == RunState.FAILED
    assert result.step_name == "00_validate"


def test_advance_on_completed_run_is_noop(seeded: dict, app_session: Session) -> None:
    run_id = uuid4()
    app_session.execute(
        text(
            """
            INSERT INTO workflow_run (id, tenant_id, engagement_id,
                                       workflow_template_id, state, ended_at)
            VALUES (:i, :t, :e, 'done', 'completed', now())
            """
        ),
        {
            "i": str(run_id), "t": str(seeded["tenant_id"]),
            "e": str(seeded["engagement_id"]),
        },
    )
    result = advance_run(app_session, run_id=run_id)
    assert result.run_state == RunState.COMPLETED


def test_resume_on_non_paused_raises(seeded: dict, app_session: Session) -> None:
    run_id = uuid4()
    app_session.execute(
        text(
            """
            INSERT INTO workflow_run (id, tenant_id, engagement_id,
                                       workflow_template_id, state)
            VALUES (:i, :t, :e, 'x', 'running')
            """
        ),
        {
            "i": str(run_id), "t": str(seeded["tenant_id"]),
            "e": str(seeded["engagement_id"]),
        },
    )
    with pytest.raises(InvalidTransition):
        resume_run(app_session, run_id=run_id)
