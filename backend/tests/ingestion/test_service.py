"""IngestionService behavior tests.

Drives the service directly against real Postgres (via the shared
pgserver fixtures) and the in-memory storage adapter + null scanner.
HTTP-layer concerns (routing, status codes) live in
``test_upload_route.py``.
"""

from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from accounting_parser.ingestion.errors import (
    DuplicateDocumentError,
    InvalidContentTypeError,
    SizeLimitExceededError,
    VirusScanError,
)
from accounting_parser.ingestion.service import IngestionService
from accounting_parser.ingestion.virus_scan import NullVirusScanner, ScanResult
from accounting_parser.storage.memory import InMemoryDocumentStoreAdapter
from tests.ingestion.conftest import SeededFirm

PDF_SAMPLE = b"%PDF-1.7\n% sample\n1 0 obj\n<< >> endobj\nxxx\n"


@dataclass
class _Harness:
    service: IngestionService
    store: InMemoryDocumentStoreAdapter
    firm: SeededFirm


@pytest.fixture
def harness(
    in_memory_store: InMemoryDocumentStoreAdapter,
    null_scanner: NullVirusScanner,
    seeded_firm: SeededFirm,
) -> _Harness:
    service = IngestionService(
        store=in_memory_store,
        scanner=null_scanner,
        bucket="test-bucket",
        max_bytes=1024 * 1024,
    )
    return _Harness(service=service, store=in_memory_store, firm=seeded_firm)


@pytest.fixture
def platform_session(superuser_engine: Engine):
    factory = sessionmaker(bind=superuser_engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()


def _ingest(
    harness: _Harness, session, filename="sample.pdf", data=PDF_SAMPLE, declared="application/pdf"
):
    return asyncio.run(
        harness.service.ingest(
            session,
            tenant_id=harness.firm.tenant_id,
            firm_id=harness.firm.firm_id,
            engagement_id=harness.firm.engagement_id,
            client_id=harness.firm.client_id,
            uploaded_by_user_id=harness.firm.user_id,
            filename=filename,
            declared_content_type=declared,
            stream=io.BytesIO(data),
        )
    )


def test_happy_path_ingest_pdf(harness: _Harness, platform_session):
    result = _ingest(harness, platform_session)
    platform_session.commit()

    # Row in the document table.
    row = platform_session.execute(
        text(
            "SELECT filename, sha256, byte_size, ingest_state, s3_key FROM document "
            "WHERE id = :id"
        ),
        {"id": str(result.document_id)},
    ).first()
    assert row is not None
    assert row[0] == "sample.pdf"
    assert bytes(row[1]).hex() == result.sha256_hex
    assert int(row[2]) == len(PDF_SAMPLE)
    assert row[3] == "uploaded"
    assert row[4] == result.object_key

    # Object stored under the expected key.
    assert result.object_key.startswith(
        f"firms/{harness.firm.firm_id}/clients/{harness.firm.client_id}/"
    )
    assert (harness.store.contents.get(("test-bucket", result.object_key))) == PDF_SAMPLE

    # Audit success event present.
    action = platform_session.execute(
        text(
            """
            SELECT action FROM audit_log_entry
            WHERE resource_id = :rid AND action = 'document.ingested'
            """
        ),
        {"rid": str(result.document_id)},
    ).scalar_one()
    assert action == "document.ingested"


def test_duplicate_rejected_with_existing_id(harness: _Harness, platform_session):
    first = _ingest(harness, platform_session)
    platform_session.commit()

    with pytest.raises(DuplicateDocumentError) as exc:
        _ingest(harness, platform_session)
    platform_session.rollback()

    assert exc.value.existing_document_id == first.document_id

    # Rejection audit event landed despite the rollback (savepoint pattern).
    count = platform_session.execute(
        text(
            """
            SELECT count(*) FROM audit_log_entry
            WHERE action = 'document.rejected'
            AND payload->>'reason_code' = 'duplicate_document'
            """
        )
    ).scalar_one()
    assert count == 1


def test_size_limit_rejected_before_storage(
    in_memory_store, null_scanner, seeded_firm, platform_session
):
    """A too-big upload never reaches the storage adapter."""
    service = IngestionService(
        store=in_memory_store,
        scanner=null_scanner,
        bucket="test-bucket",
        max_bytes=1024,  # 1 KB
    )
    big = b"%PDF-1.7\n" + b"A" * 2048
    with pytest.raises(SizeLimitExceededError):
        asyncio.run(
            service.ingest(
                platform_session,
                tenant_id=seeded_firm.tenant_id,
                firm_id=seeded_firm.firm_id,
                engagement_id=seeded_firm.engagement_id,
                client_id=seeded_firm.client_id,
                uploaded_by_user_id=seeded_firm.user_id,
                filename="big.pdf",
                declared_content_type="application/pdf",
                stream=io.BytesIO(big),
            )
        )
    platform_session.rollback()

    # Nothing stored.
    assert in_memory_store.contents == {}

    # Rejection event committed.
    reason = platform_session.execute(
        text(
            """
            SELECT payload->>'reason_code'
            FROM audit_log_entry
            WHERE action = 'document.rejected'
            ORDER BY sequence_number DESC LIMIT 1
            """
        )
    ).scalar_one()
    assert reason == "size_limit_exceeded"


def test_invalid_content_type_rejected(harness: _Harness, platform_session):
    """Unsupported content type rejected before storage."""
    with pytest.raises(InvalidContentTypeError):
        _ingest(
            harness,
            platform_session,
            filename="bad.exe",
            data=b"MZ\x90\x00\x03\x00\x00\x00",  # Windows PE header
            declared="application/octet-stream",
        )
    platform_session.rollback()
    assert harness.store.contents == {}


def test_virus_detected_quarantined_and_not_persisted(
    in_memory_store, seeded_firm, platform_session
):
    """Infected upload lands in quarantine prefix, no document row inserted."""

    class _InfectedScanner:
        def scan(self, stream):
            while stream.read(65536):
                pass
            return ScanResult(is_clean=False, signature="TestSig-EICAR", scanner_version="fake-1")

    service = IngestionService(
        store=in_memory_store,
        scanner=_InfectedScanner(),
        bucket="test-bucket",
        max_bytes=1024 * 1024,
    )
    with pytest.raises(VirusScanError):
        asyncio.run(
            service.ingest(
                platform_session,
                tenant_id=seeded_firm.tenant_id,
                firm_id=seeded_firm.firm_id,
                engagement_id=seeded_firm.engagement_id,
                client_id=seeded_firm.client_id,
                uploaded_by_user_id=seeded_firm.user_id,
                filename="eicar.pdf",
                declared_content_type="application/pdf",
                stream=io.BytesIO(PDF_SAMPLE),
            )
        )
    platform_session.rollback()

    # No document row.
    count = platform_session.execute(text("SELECT count(*) FROM document")).scalar_one()
    assert count == 0

    # Quarantine object DID land (incident response can retrieve).
    quarantine_keys = [
        k
        for (_b, k) in in_memory_store.contents
        if k.startswith(f"firms/{seeded_firm.firm_id}/quarantine/")
    ]
    assert len(quarantine_keys) == 1

    # Audit rejection has the signature captured.
    payload = platform_session.execute(
        text(
            """
            SELECT payload
            FROM audit_log_entry
            WHERE action = 'document.rejected'
            ORDER BY sequence_number DESC LIMIT 1
            """
        )
    ).scalar_one()
    import json

    parsed = json.loads(payload) if isinstance(payload, str) else payload
    assert parsed["reason_code"] == "virus_detected"
    assert parsed["scan_signature"] == "TestSig-EICAR"


def test_empty_upload_rejected(harness: _Harness, platform_session):
    with pytest.raises(InvalidContentTypeError):
        _ingest(harness, platform_session, data=b"")
    platform_session.rollback()


def test_same_content_same_filename_different_client_allowed(
    in_memory_store, null_scanner, superuser_engine, seeded_firm, platform_session
):
    """Dedup is scoped to (tenant, client) — another client can re-ingest."""
    # Create a second client under the same tenant+firm.
    second_client_id = __import__("uuid").uuid4()
    second_engagement_id = __import__("uuid").uuid4()
    platform_session.execute(
        text(
            "INSERT INTO client (id, tenant_id, firm_id, name) "
            "VALUES (:id, :tid, :fid, 'Other Client')"
        ),
        {
            "id": str(second_client_id),
            "tid": str(seeded_firm.tenant_id),
            "fid": str(seeded_firm.firm_id),
        },
    )
    platform_session.execute(
        text(
            """
            INSERT INTO engagement (id, tenant_id, client_id, name, engagement_type)
            VALUES (:id, :tid, :cid, 'Other', 'tax_return')
            """
        ),
        {
            "id": str(second_engagement_id),
            "tid": str(seeded_firm.tenant_id),
            "cid": str(second_client_id),
        },
    )
    platform_session.commit()

    service = IngestionService(
        store=in_memory_store,
        scanner=null_scanner,
        bucket="test-bucket",
        max_bytes=1024 * 1024,
    )

    # Ingest for client 1.
    asyncio.run(
        service.ingest(
            platform_session,
            tenant_id=seeded_firm.tenant_id,
            firm_id=seeded_firm.firm_id,
            engagement_id=seeded_firm.engagement_id,
            client_id=seeded_firm.client_id,
            uploaded_by_user_id=seeded_firm.user_id,
            filename="same.pdf",
            declared_content_type="application/pdf",
            stream=io.BytesIO(PDF_SAMPLE),
        )
    )
    platform_session.commit()

    # Same bytes, same filename, different client — must succeed.
    result_2 = asyncio.run(
        service.ingest(
            platform_session,
            tenant_id=seeded_firm.tenant_id,
            firm_id=seeded_firm.firm_id,
            engagement_id=second_engagement_id,
            client_id=second_client_id,
            uploaded_by_user_id=seeded_firm.user_id,
            filename="same.pdf",
            declared_content_type="application/pdf",
            stream=io.BytesIO(PDF_SAMPLE),
        )
    )
    platform_session.commit()

    assert result_2.document_id is not None
    count = platform_session.execute(text("SELECT count(*) FROM document")).scalar_one()
    assert count == 2
