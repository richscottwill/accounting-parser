"""Tests for Tasks 23 (PBC portal), 27 (observability), 30 (compliance)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from accounting_parser.auth.audit import emit_audit_event
from accounting_parser.compliance.audit_export import (
    access_review_report,
    export_audit_trail_csv,
    export_audit_trail_json,
    sign_export_hmac,
)
from accounting_parser.compliance.wisp import (
    WISPContext,
    generate_wisp_markdown,
)
from accounting_parser.db.session import set_tenant_context
from accounting_parser.observability.metrics import (
    FakeMetrics,
    Metric,
    hashed_tenant,
)
from accounting_parser.observability.redact import redact, redact_text
from accounting_parser.portal.pbc import (
    InvalidPBCTransition,
    PBCCreateRequest,
    PBCStatus,
    can_transition,
    create_pbc_request,
    transition_pbc_request,
)


# ---------------------------------------------------------------------------
# Observability / redaction
# ---------------------------------------------------------------------------

def test_redact_ssn_dashed() -> None:
    s = "taxpayer SSN 123-45-6789"
    assert redact_text(s) == "taxpayer SSN ***-**-6789"


def test_redact_ssn_flat() -> None:
    assert redact_text("123456789 is an SSN") == "***-**-6789 is an SSN"


def test_redact_ein() -> None:
    assert redact_text("EIN 12-3456789 on form") == "EIN **-***6789 on form"


def test_redact_bank_account() -> None:
    assert "****3456" in redact_text("account 1234563456 at Chase")


def test_redact_recursive_structure() -> None:
    payload = {
        "ok": "no SSN here",
        "nested": {"ssn": "123-45-6789"},
        "list": ["EIN 12-3456789", "neutral"],
    }
    out = redact(payload)
    assert out["nested"]["ssn"] == "***-**-6789"
    assert "**-***6789" in out["list"][0]
    assert out["list"][1] == "neutral"


def test_metric_hash_is_stable() -> None:
    t = uuid4()
    assert hashed_tenant(t) == hashed_tenant(t)
    assert hashed_tenant(str(t)) == hashed_tenant(t)


def test_fake_metrics_collects() -> None:
    m = FakeMetrics()
    m.emit(Metric(name="parse_success", value=1.0))
    m.emit(Metric(name="parse_success", value=0.0))
    assert len(m.emitted) == 2


# ---------------------------------------------------------------------------
# Compliance — WISP
# ---------------------------------------------------------------------------

def test_wisp_contains_firm_name_and_admin() -> None:
    md = generate_wisp_markdown(
        WISPContext(
            firm_name="Acme Tax LLC",
            admin_name="Alice Admin",
            admin_email="alice@acme.example",
            admin_ptin_masked="****1234",
        )
    )
    assert "Acme Tax LLC" in md
    assert "Alice Admin" in md
    assert "****1234" in md
    assert "Purpose and Scope" in md
    assert "Incident Response" in md


# ---------------------------------------------------------------------------
# PBC + audit trail (DB-backed)
# ---------------------------------------------------------------------------

@pytest.fixture
def seeded(migrated_engine: Engine) -> dict:
    tenant_id = uuid4()
    firm_id = uuid4()
    user_id = uuid4()
    client_id = uuid4()
    engagement_id = uuid4()
    nm = f"Portal Co {tenant_id.hex[:8]}"

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
                    id, tenant_id, firm_id, cognito_sub, email, role, mfa_required,
                    ptin_masked
                ) VALUES (:i, :t, :f, :s, :e, 'firm_administrator', true, '****9999')
                """
            ),
            {
                "i": str(user_id), "t": str(tenant_id), "f": str(firm_id),
                "s": f"sub-{user_id}", "e": f"admin-{tenant_id.hex[:6]}@example.com",
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
        "firm_id": firm_id,
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


def test_pbc_state_machine_allowed_transitions() -> None:
    assert can_transition(PBCStatus.OPEN, PBCStatus.SENT)
    assert can_transition(PBCStatus.SENT, PBCStatus.RECEIVED)
    assert not can_transition(PBCStatus.CLOSED, PBCStatus.SENT)
    assert not can_transition(PBCStatus.WAIVED, PBCStatus.RECEIVED)


def test_pbc_create_and_transition(seeded: dict, app_session: Session) -> None:
    pbc_id = create_pbc_request(
        app_session,
        tenant_id=seeded["tenant_id"],
        actor_user_id=seeded["user_id"],
        req=PBCCreateRequest(
            engagement_id=seeded["engagement_id"],
            title="Bank statements Q4",
        ),
    )
    transition_pbc_request(
        app_session,
        tenant_id=seeded["tenant_id"],
        actor_user_id=seeded["user_id"],
        pbc_id=pbc_id,
        to=PBCStatus.SENT,
    )
    transition_pbc_request(
        app_session,
        tenant_id=seeded["tenant_id"],
        actor_user_id=seeded["user_id"],
        pbc_id=pbc_id,
        to=PBCStatus.RECEIVED,
    )
    current = app_session.execute(
        text("SELECT status FROM pbc_request WHERE id = :i"),
        {"i": str(pbc_id)},
    ).scalar()
    assert current == "received"


def test_pbc_illegal_transition_raises(seeded: dict, app_session: Session) -> None:
    pbc_id = create_pbc_request(
        app_session,
        tenant_id=seeded["tenant_id"],
        actor_user_id=seeded["user_id"],
        req=PBCCreateRequest(
            engagement_id=seeded["engagement_id"],
            title="W-2s",
        ),
    )
    with pytest.raises(InvalidPBCTransition):
        transition_pbc_request(
            app_session,
            tenant_id=seeded["tenant_id"],
            actor_user_id=seeded["user_id"],
            pbc_id=pbc_id,
            to=PBCStatus.RECEIVED,  # can't jump from OPEN directly
        )


def test_audit_export_signed(seeded: dict, app_session: Session, migrated_engine: Engine) -> None:
    # Emit a couple of entries so the export has content.
    emit_audit_event(
        app_session,
        action="test.event",
        tenant_id=seeded["tenant_id"],
        resource_type="engagement",
        resource_id=seeded["engagement_id"],
        actor_user_id=seeded["user_id"],
        payload={"note": "first"},
    )
    emit_audit_event(
        app_session,
        action="test.event",
        tenant_id=seeded["tenant_id"],
        resource_type="engagement",
        resource_id=seeded["engagement_id"],
        actor_user_id=seeded["user_id"],
        payload={"note": "second"},
    )
    app_session.commit()

    # Use the superuser engine so we're not constrained by RLS for verify.
    SessionLocal = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    session2 = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        json_blob = export_audit_trail_json(
            session2,
            tenant_id=seeded["tenant_id"],
            start=now - timedelta(hours=1),
            end=now + timedelta(hours=1),
        )
        csv_blob = export_audit_trail_csv(
            session2,
            tenant_id=seeded["tenant_id"],
            start=now - timedelta(hours=1),
            end=now + timedelta(hours=1),
        )
        report = access_review_report(
            session2,
            tenant_id=seeded["tenant_id"],
            start=now - timedelta(hours=1),
            end=now + timedelta(hours=1),
        )
    finally:
        session2.close()
    assert '"action": "test.event"' in json_blob
    assert "test.event" in csv_blob
    assert len(report) >= 1

    sig = sign_export_hmac(json_blob, secret=b"test-only-key")
    assert len(sig) == 64  # sha256 hex
    # Signatures are deterministic.
    assert sig == sign_export_hmac(json_blob, secret=b"test-only-key")
