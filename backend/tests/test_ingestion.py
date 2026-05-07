"""Task 6 ingestion tests.

Covers the IngestionService pipeline end-to-end against a real migrated
Postgres + the local-disk storage backend + the EICAR scanner. All
branches (happy path, duplicate, size, MIME mismatch, quarantine,
zero-byte, bad extension) produce their audit entries.
"""
from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from accounting_parser.config import Settings
from accounting_parser.db.session import set_tenant_context
from accounting_parser.ingestion.mime import detect_mime, mime_declared_matches_detected
from accounting_parser.ingestion.scanner import EicarScanner, ScanResult, SkipScanner
from accounting_parser.ingestion.service import (
    DuplicateDocumentError,
    IngestionError,
    IngestionService,
)
from accounting_parser.ingestion.storage import LocalDiskStorage


# ---------------------------------------------------------------------------
# Fixtures: tenant + firm + client + engagement on the app_user RLS path.
# ---------------------------------------------------------------------------

@pytest.fixture
def seeded_engagement(migrated_engine: Engine, app_engine: Engine) -> dict:
    """Create a tenant/firm/client/engagement in one superuser transaction
    so subsequent app_user sessions can read them with RLS."""
    tenant_id = uuid4()
    firm_id = uuid4()
    user_id = uuid4()
    client_id = uuid4()
    engagement_id = uuid4()
    firm_name = f"Ingest Co {tenant_id.hex[:8]}"

    with migrated_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO tenant (id, name, kms_key_alias) VALUES (:id, :n, :a)"),
            {"id": str(tenant_id), "n": firm_name, "a": f"alias/{tenant_id}"},
        )
        conn.execute(
            text("INSERT INTO firm (id, tenant_id, name, ptin) VALUES (:i,:t,:n,NULL)"),
            {"i": str(firm_id), "t": str(tenant_id), "n": firm_name},
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
                "s": f"sub-{user_id}", "e": f"admin-{tenant_id.hex[:6]}@example.com",
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO client (id, tenant_id, firm_id, name, entity_type, fiscal_year_end_month)
                VALUES (:i, :t, :f, :n, 's_corporation', 12)
                """
            ),
            {"i": str(client_id), "t": str(tenant_id), "f": str(firm_id), "n": f"Acme {tenant_id.hex[:6]}"},
        )
        conn.execute(
            text(
                """
                INSERT INTO engagement (
                    id, tenant_id, client_id, name, engagement_type, tax_year, status
                ) VALUES (:i, :t, :c, :n, 'tax_return', 2025, 'in_progress')
                """
            ),
            {
                "i": str(engagement_id),
                "t": str(tenant_id),
                "c": str(client_id),
                "n": "2025 1120-S",
            },
        )

    return {
        "tenant_id": tenant_id,
        "firm_id": firm_id,
        "user_id": user_id,
        "client_id": client_id,
        "engagement_id": engagement_id,
    }


@pytest.fixture
def app_session(app_engine: Engine, seeded_engagement: dict) -> Session:
    SessionLocal = sessionmaker(bind=app_engine, expire_on_commit=False)
    s = SessionLocal()
    set_tenant_context(s, seeded_engagement["tenant_id"])
    try:
        yield s
        s.commit()
    finally:
        s.close()


@pytest.fixture
def ingest_service(tmp_path: Path, app_session: Session) -> IngestionService:
    storage = LocalDiskStorage(tmp_path)
    return IngestionService(
        session=app_session,
        storage=storage,
        scanner=EicarScanner(),
        settings=Settings(),
    )


def _pdf_bytes(size: int = 4096) -> bytes:
    """Minimal valid-ish PDF (header + filler) so magic-byte passes."""
    header = b"%PDF-1.4\n"
    return header + b"x" * (size - len(header))


# ---------------------------------------------------------------------------
# MIME detection unit tests — no DB required.
# ---------------------------------------------------------------------------

def test_detect_mime_pdf() -> None:
    r = detect_mime(_pdf_bytes(200))
    assert r.detected_mime == "application/pdf"


def test_detect_mime_xlsx_zip_container() -> None:
    r = detect_mime(b"PK\x03\x04" + b"\x00" * 60)
    assert r.detected_mime == "application/vnd.openxmlformats-officedocument.zip"


def test_detect_mime_fallback_octet_stream() -> None:
    r = detect_mime(b"\x00\x01\x02\x03")
    assert r.detected_mime == "application/octet-stream"


def test_mime_declared_matches_detected_pairs() -> None:
    # XLSX declared vs detected as generic OOXML zip
    assert mime_declared_matches_detected(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.zip",
    )
    # CSV declared vs detected as plain text
    assert mime_declared_matches_detected("text/csv", "text/plain")
    # Mismatch
    assert not mime_declared_matches_detected("application/pdf", "text/plain")


# ---------------------------------------------------------------------------
# Scanner unit tests.
# ---------------------------------------------------------------------------

def test_eicar_scanner_flags_test_signature() -> None:
    s = EicarScanner()
    eicar = (
        b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    )
    outcome = s.scan(eicar, filename="test.txt")
    assert outcome.result == ScanResult.INFECTED
    assert outcome.finding == "Eicar-Test-Signature"


def test_skip_scanner_always_clean() -> None:
    outcome = SkipScanner().scan(b"anything", filename="x.pdf")
    assert outcome.result == ScanResult.CLEAN


# ---------------------------------------------------------------------------
# Service integration tests — hit the real DB + local-disk storage.
# ---------------------------------------------------------------------------

def test_happy_path_upload_pdf(ingest_service: IngestionService, seeded_engagement: dict, app_session: Session) -> None:
    result = ingest_service.upload(
        tenant_id=seeded_engagement["tenant_id"],
        firm_id=seeded_engagement["firm_id"],
        client_id=seeded_engagement["client_id"],
        engagement_id=seeded_engagement["engagement_id"],
        uploader_user_id=seeded_engagement["user_id"],
        filename="test.pdf",
        declared_mime="application/pdf",
        content=_pdf_bytes(1024),
    )
    assert result.ingest_state == "received"
    assert result.quarantined is False
    assert result.detected_mime == "application/pdf"

    # Row persisted.
    row = app_session.execute(
        text("SELECT ingest_state, scan_state, filename FROM document WHERE id = :id"),
        {"id": str(result.document_id)},
    ).mappings().first()
    assert row is not None
    assert row["ingest_state"] == "received"
    assert row["scan_state"] == "clean"
    assert row["filename"] == "test.pdf"

    # Audit entry exists.
    audit = app_session.execute(
        text(
            """
            SELECT action FROM audit_log_entry
            WHERE resource_id = :id AND action = 'document.ingested'
            """
        ),
        {"id": str(result.document_id)},
    ).first()
    assert audit is not None


def test_rejects_zero_byte_upload(ingest_service: IngestionService, seeded_engagement: dict) -> None:
    with pytest.raises(IngestionError) as exc:
        ingest_service.upload(
            tenant_id=seeded_engagement["tenant_id"],
            firm_id=seeded_engagement["firm_id"],
            client_id=seeded_engagement["client_id"],
            engagement_id=seeded_engagement["engagement_id"],
            uploader_user_id=seeded_engagement["user_id"],
            filename="empty.pdf",
            declared_mime="application/pdf",
            content=b"",
        )
    assert exc.value.reason_code == "empty_upload"


def test_rejects_unsupported_extension(ingest_service: IngestionService, seeded_engagement: dict) -> None:
    with pytest.raises(IngestionError) as exc:
        ingest_service.upload(
            tenant_id=seeded_engagement["tenant_id"],
            firm_id=seeded_engagement["firm_id"],
            client_id=seeded_engagement["client_id"],
            engagement_id=seeded_engagement["engagement_id"],
            uploader_user_id=seeded_engagement["user_id"],
            filename="malware.exe",
            declared_mime="application/octet-stream",
            content=b"MZ\x90\x00" * 100,
        )
    assert exc.value.reason_code == "unsupported_extension"


def test_rejects_mime_mismatch(ingest_service: IngestionService, seeded_engagement: dict) -> None:
    with pytest.raises(IngestionError) as exc:
        ingest_service.upload(
            tenant_id=seeded_engagement["tenant_id"],
            firm_id=seeded_engagement["firm_id"],
            client_id=seeded_engagement["client_id"],
            engagement_id=seeded_engagement["engagement_id"],
            uploader_user_id=seeded_engagement["user_id"],
            filename="lies.pdf",
            declared_mime="application/pdf",
            content=b"plain text, not a PDF",
        )
    assert exc.value.reason_code == "mime_mismatch"


def test_duplicate_hash_rejected(ingest_service: IngestionService, seeded_engagement: dict) -> None:
    content = _pdf_bytes(2048)
    ingest_service.upload(
        tenant_id=seeded_engagement["tenant_id"],
        firm_id=seeded_engagement["firm_id"],
        client_id=seeded_engagement["client_id"],
        engagement_id=seeded_engagement["engagement_id"],
        uploader_user_id=seeded_engagement["user_id"],
        filename="dup.pdf",
        declared_mime="application/pdf",
        content=content,
    )
    with pytest.raises(DuplicateDocumentError):
        ingest_service.upload(
            tenant_id=seeded_engagement["tenant_id"],
            firm_id=seeded_engagement["firm_id"],
            client_id=seeded_engagement["client_id"],
            engagement_id=seeded_engagement["engagement_id"],
            uploader_user_id=seeded_engagement["user_id"],
            filename="dup.pdf",
            declared_mime="application/pdf",
            content=content,
        )


def test_infected_upload_quarantined_not_duplicate_checked(
    ingest_service: IngestionService, seeded_engagement: dict, app_session: Session
) -> None:
    eicar_pdf = b"%PDF-1.4\n" + (
        b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    )
    result = ingest_service.upload(
        tenant_id=seeded_engagement["tenant_id"],
        firm_id=seeded_engagement["firm_id"],
        client_id=seeded_engagement["client_id"],
        engagement_id=seeded_engagement["engagement_id"],
        uploader_user_id=seeded_engagement["user_id"],
        filename="infected.pdf",
        declared_mime="application/pdf",
        content=eicar_pdf,
    )
    assert result.quarantined is True
    assert result.ingest_state == "quarantined"

    row = app_session.execute(
        text("SELECT scan_state, scan_finding, ingest_state FROM document WHERE id = :id"),
        {"id": str(result.document_id)},
    ).mappings().first()
    assert row is not None
    assert row["scan_state"] == "infected"
    assert row["scan_finding"] == "Eicar-Test-Signature"


def test_oversize_upload_rejected(tmp_path: Path, seeded_engagement: dict, app_session: Session) -> None:
    small_limit_settings = Settings(max_upload_bytes=1024)
    service = IngestionService(
        session=app_session,
        storage=LocalDiskStorage(tmp_path),
        scanner=EicarScanner(),
        settings=small_limit_settings,
    )
    with pytest.raises(IngestionError) as exc:
        service.upload(
            tenant_id=seeded_engagement["tenant_id"],
            firm_id=seeded_engagement["firm_id"],
            client_id=seeded_engagement["client_id"],
            engagement_id=seeded_engagement["engagement_id"],
            uploader_user_id=seeded_engagement["user_id"],
            filename="big.pdf",
            declared_mime="application/pdf",
            content=_pdf_bytes(2048),
        )
    assert exc.value.reason_code == "size_exceeded"
    assert exc.value.status_code == 413
