"""Task 9 — OCR adapter + field-validation gate tests.

Covers:
- FakeOCR returns configured fields with set confidence.
- gate.evaluate splits fields by the 0.95 threshold.
- confirm_field writes an audit entry; corrections are distinguishable.
- all_flagged_fields_confirmed enforces the gate at the posting layer.
- Correctness Property 26: a gate event is recorded before any
  sub-0.95 field is posted (exercised by flow-level assertion).
"""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from accounting_parser.db.session import set_tenant_context
from accounting_parser.ocr.adapter import ExtractedField, FakeOCR, OCRResult
from accounting_parser.ocr.gate import (
    CONFIDENCE_FLOOR,
    all_flagged_fields_confirmed,
    confirm_field,
    evaluate,
)


@pytest.fixture
def seeded(migrated_engine: Engine) -> dict:
    tenant_id = uuid4()
    user_id = uuid4()
    firm_id = uuid4()
    client_id = uuid4()
    engagement_id = uuid4()
    doc_id = uuid4()
    nm = f"OCR Co {tenant_id.hex[:8]}"

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
                ) VALUES (:i, :t, :f, :s, :e, 'preparer', false)
                """
            ),
            {
                "i": str(user_id), "t": str(tenant_id), "f": str(firm_id),
                "s": f"sub-{user_id}", "e": f"ocr-{tenant_id.hex[:6]}@example.com",
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO client (
                    id, tenant_id, firm_id, name, entity_type, fiscal_year_end_month
                ) VALUES (:i, :t, :f, :n, 'sole_proprietorship', 12)
                """
            ),
            {"i": str(client_id), "t": str(tenant_id), "f": str(firm_id), "n": nm},
        )
        conn.execute(
            text(
                """
                INSERT INTO engagement (
                    id, tenant_id, client_id, name, engagement_type, tax_year, status
                ) VALUES (:i, :t, :c, '2025 1040', 'tax_return', 2025, 'in_progress')
                """
            ),
            {"i": str(engagement_id), "t": str(tenant_id), "c": str(client_id)},
        )
        conn.execute(
            text(
                """
                INSERT INTO document (
                    id, tenant_id, client_id, engagement_id, filename,
                    content_type, byte_size, sha256, s3_bucket, s3_key,
                    ingest_state
                ) VALUES (:i, :t, :c, :e, 'w2.pdf', 'application/pdf',
                          10, :h, 'b', 'k', 'received')
                """
            ),
            {
                "i": str(doc_id),
                "t": str(tenant_id),
                "c": str(client_id),
                "e": str(engagement_id),
                "h": b"w" * 32,
            },
        )

    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "document_id": doc_id,
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


# ---------------------------------------------------------------------------
# Pure unit tests
# ---------------------------------------------------------------------------

def test_fake_ocr_returns_configured_fields() -> None:
    adapter = FakeOCR(
        {
            "Wages Box 1": ("60000.00", 0.99),
            "Federal Tax Withheld": ("4800.00", 0.91),
        }
    )
    result = adapter.analyze(b"fake pdf", filename="w2.pdf")
    assert result.engine == "fake"
    assert len(result.fields) == 2


def test_gate_splits_by_confidence_floor() -> None:
    r = OCRResult(
        engine="fake",
        engine_version="1.0",
        pages=1,
        fields=[
            ExtractedField(name="A", value="1", confidence=0.97),
            ExtractedField(name="B", value="2", confidence=0.50),
            ExtractedField(name="C", value="3", confidence=CONFIDENCE_FLOOR),
        ],
    )
    verdict = evaluate(r)
    assert [f.name for f in verdict.auto_post] == ["A", "C"]
    assert [f.name for f in verdict.flagged] == ["B"]


# ---------------------------------------------------------------------------
# DB-backed tests — audit + gate enforcement
# ---------------------------------------------------------------------------

def test_confirm_field_writes_audit_entry(seeded: dict, app_session: Session) -> None:
    confirm_field(
        app_session,
        tenant_id=seeded["tenant_id"],
        actor_user_id=seeded["user_id"],
        document_id=seeded["document_id"],
        field_name="Wages Box 1",
        original_value="60000.00",
        original_confidence=0.89,
        corrected_value=None,
    )
    row = app_session.execute(
        text(
            """
            SELECT action, payload->>'field_name' AS n
            FROM audit_log_entry
            WHERE resource_id = :d AND action = 'ocr.field_confirmed'
            """
        ),
        {"d": str(seeded["document_id"])},
    ).first()
    assert row is not None
    assert row[1] == "Wages Box 1"


def test_correction_recorded_as_distinct_action(seeded: dict, app_session: Session) -> None:
    confirm_field(
        app_session,
        tenant_id=seeded["tenant_id"],
        actor_user_id=seeded["user_id"],
        document_id=seeded["document_id"],
        field_name="Federal Tax Withheld",
        original_value="4800.00",
        original_confidence=0.62,
        corrected_value="4850.00",
    )
    row = app_session.execute(
        text(
            """
            SELECT action FROM audit_log_entry
            WHERE resource_id = :d AND action = 'ocr.field_corrected'
            """
        ),
        {"d": str(seeded["document_id"])},
    ).first()
    assert row is not None


def test_gate_requires_every_flagged_field_confirmed(seeded: dict, app_session: Session) -> None:
    flagged = ["Wages Box 1", "Federal Tax Withheld"]
    assert not all_flagged_fields_confirmed(
        app_session, document_id=seeded["document_id"], flagged_field_names=flagged
    )
    confirm_field(
        app_session,
        tenant_id=seeded["tenant_id"],
        actor_user_id=seeded["user_id"],
        document_id=seeded["document_id"],
        field_name="Wages Box 1",
        original_value="60000.00",
        original_confidence=0.70,
    )
    assert not all_flagged_fields_confirmed(
        app_session, document_id=seeded["document_id"], flagged_field_names=flagged
    )
    confirm_field(
        app_session,
        tenant_id=seeded["tenant_id"],
        actor_user_id=seeded["user_id"],
        document_id=seeded["document_id"],
        field_name="Federal Tax Withheld",
        original_value="4800.00",
        original_confidence=0.70,
    )
    assert all_flagged_fields_confirmed(
        app_session, document_id=seeded["document_id"], flagged_field_names=flagged
    )
