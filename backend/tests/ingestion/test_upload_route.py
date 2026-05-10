"""HTTP layer tests for document upload.

Exercises the FastAPI route including auth middleware, RLS-pinned
DB session, and error-code mapping. Uses the in-memory storage +
null scanner from conftest.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from tests.ingestion.conftest import SeededFirm

PDF_SAMPLE = b"%PDF-1.7\n% Upload route test\n1 0 obj\n<< >> endobj\n"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_upload_requires_auth(ingestion_client: TestClient, seeded_firm: SeededFirm):
    """No token → 401 (middleware rejects before the route runs)."""
    response = ingestion_client.post(
        f"/engagements/{seeded_firm.engagement_id}/documents",
        files={"file": ("x.pdf", b"%PDF-1.7\n", "application/pdf")},
    )
    assert response.status_code == 401


def test_upload_happy_path(
    ingestion_client: TestClient,
    seeded_firm: SeededFirm,
    auth_token: str,
    in_memory_store,
):
    response = ingestion_client.post(
        f"/engagements/{seeded_firm.engagement_id}/documents",
        files={"file": ("quarterly.pdf", PDF_SAMPLE, "application/pdf")},
        headers=_headers(auth_token),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["content_type"] == "application/pdf"
    assert body["byte_size"] == len(PDF_SAMPLE)
    assert len(body["sha256_hex"]) == 64

    # Storage saw the bytes.
    stored = list(in_memory_store.contents.values())
    assert len(stored) == 1
    assert stored[0] == PDF_SAMPLE


def test_upload_duplicate_returns_409_with_existing_id(
    ingestion_client: TestClient, seeded_firm: SeededFirm, auth_token: str
):
    first = ingestion_client.post(
        f"/engagements/{seeded_firm.engagement_id}/documents",
        files={"file": ("a.pdf", PDF_SAMPLE, "application/pdf")},
        headers=_headers(auth_token),
    )
    assert first.status_code == 201
    first_id = first.json()["document_id"]

    second = ingestion_client.post(
        f"/engagements/{seeded_firm.engagement_id}/documents",
        files={"file": ("b.pdf", PDF_SAMPLE, "application/pdf")},
        headers=_headers(auth_token),
    )
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["existing_document_id"] == first_id


def test_upload_rejects_disallowed_content_type(
    ingestion_client: TestClient, seeded_firm: SeededFirm, auth_token: str
):
    response = ingestion_client.post(
        f"/engagements/{seeded_firm.engagement_id}/documents",
        files={"file": ("bad.exe", b"MZ\x90\x00", "application/octet-stream")},
        headers=_headers(auth_token),
    )
    assert response.status_code == 415


def test_upload_rejects_oversize(
    ingestion_client: TestClient,
    ingestion_settings,
    seeded_firm: SeededFirm,
    auth_token: str,
):
    """ingest_max_bytes is 1 MB in test settings; send 2 MB."""
    big = b"%PDF-1.7\n" + b"x" * (2 * 1024 * 1024)
    response = ingestion_client.post(
        f"/engagements/{seeded_firm.engagement_id}/documents",
        files={"file": ("big.pdf", big, "application/pdf")},
        headers=_headers(auth_token),
    )
    assert response.status_code == 413


def test_upload_to_missing_engagement_404(ingestion_client: TestClient, auth_token: str):
    import uuid

    response = ingestion_client.post(
        f"/engagements/{uuid.uuid4()}/documents",
        files={"file": ("x.pdf", PDF_SAMPLE, "application/pdf")},
        headers=_headers(auth_token),
    )
    assert response.status_code == 404


def test_list_documents_returns_uploaded(
    ingestion_client: TestClient,
    seeded_firm: SeededFirm,
    auth_token: str,
):
    ingestion_client.post(
        f"/engagements/{seeded_firm.engagement_id}/documents",
        files={"file": ("q.pdf", PDF_SAMPLE, "application/pdf")},
        headers=_headers(auth_token),
    )
    response = ingestion_client.get(
        f"/engagements/{seeded_firm.engagement_id}/documents",
        headers=_headers(auth_token),
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["documents"]) == 1
    assert body["documents"][0]["filename"] == "q.pdf"


def test_get_document_metadata(
    ingestion_client: TestClient,
    seeded_firm: SeededFirm,
    auth_token: str,
):
    up = ingestion_client.post(
        f"/engagements/{seeded_firm.engagement_id}/documents",
        files={"file": ("metadata.pdf", PDF_SAMPLE, "application/pdf")},
        headers=_headers(auth_token),
    )
    doc_id = up.json()["document_id"]
    response = ingestion_client.get(
        f"/documents/{doc_id}",
        headers=_headers(auth_token),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "metadata.pdf"
    assert body["byte_size"] == len(PDF_SAMPLE)


def test_get_document_content_streams_bytes(
    ingestion_client: TestClient,
    seeded_firm: SeededFirm,
    auth_token: str,
):
    up = ingestion_client.post(
        f"/engagements/{seeded_firm.engagement_id}/documents",
        files={"file": ("content.pdf", PDF_SAMPLE, "application/pdf")},
        headers=_headers(auth_token),
    )
    doc_id = up.json()["document_id"]
    response = ingestion_client.get(
        f"/documents/{doc_id}/content",
        headers=_headers(auth_token),
    )
    assert response.status_code == 200
    assert response.content == PDF_SAMPLE
    assert 'filename="content.pdf"' in response.headers["content-disposition"]


def test_get_document_not_found(ingestion_client: TestClient, auth_token: str):
    import uuid

    response = ingestion_client.get(
        f"/documents/{uuid.uuid4()}",
        headers=_headers(auth_token),
    )
    assert response.status_code == 404


def test_cross_tenant_upload_forbidden(
    ingestion_client: TestClient,
    ingestion_memory_adapter,
    seeded_firm: SeededFirm,
    superuser_engine: Engine,
):
    """A token issued for Tenant A cannot upload to Engagement in Tenant B.

    Seeds a second tenant's engagement, mints a token for it, and
    tries to upload to the ORIGINAL engagement. Must 404 because
    the Engagement isn't visible to the second tenant.
    """
    import asyncio
    import uuid

    from accounting_parser.auth.adapter import (
        AuthenticatedUser,
        AuthProvider,
        PasskeyCredential,
        UserRole,
    )

    # Seed a distinct tenant + user.
    factory = sessionmaker(bind=superuser_engine, expire_on_commit=False)
    session = factory()
    other_tenant = uuid.uuid4()
    other_firm = uuid.uuid4()
    other_user = uuid.uuid4()
    session.execute(
        text("INSERT INTO tenant (id, name) VALUES (:id, 'Other Tenant')"),
        {"id": str(other_tenant)},
    )
    session.execute(
        text("INSERT INTO firm (id, tenant_id, name) VALUES (:id, :tid, 'Other Firm')"),
        {"id": str(other_firm), "tid": str(other_tenant)},
    )
    session.execute(
        text(
            """
            INSERT INTO app_user (id, tenant_id, firm_id, cognito_sub, email, role)
            VALUES (:id, :tid, :fid, :sub, :em, 'firm_administrator')
            """
        ),
        {
            "id": str(other_user),
            "tid": str(other_tenant),
            "fid": str(other_firm),
            "sub": f"memory-{other_user}",
            "em": "other@firm.test",
        },
    )
    session.commit()
    session.close()

    user = AuthenticatedUser(
        user_id=other_user,
        tenant_id=other_tenant,
        firm_id=other_firm,
        email="other@firm.test",
        role=UserRole.FIRM_ADMINISTRATOR,
        external_id=f"memory-{other_user}",
        external_provider=AuthProvider.AUTHENTIK,
        session_expires_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        passkey_verified=True,
    )
    credential = PasskeyCredential(credential_id=b"c", public_key=b"p", sign_count=0, aaguid=None)
    token = asyncio.run(
        ingestion_memory_adapter.issue_session(
            user=user, credential=credential, session_duration_seconds=3600
        )
    )

    response = ingestion_client.post(
        f"/engagements/{seeded_firm.engagement_id}/documents",  # BELONGS TO seeded_firm
        files={"file": ("cross.pdf", PDF_SAMPLE, "application/pdf")},
        headers={"Authorization": f"Bearer {token.token}"},
    )
    # RLS filters the engagement lookup; route returns 404 (the
    # engagement isn't visible from the other tenant's context).
    assert response.status_code == 404
