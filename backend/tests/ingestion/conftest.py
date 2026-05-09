"""Ingestion test fixtures.

Adds:

- ``in_memory_store`` — a fresh ``InMemoryDocumentStoreAdapter`` per test.
- ``null_scanner``    — a fresh ``NullVirusScanner`` per test.
- ``seeded_firm``     — a tenant + firm + client + engagement + user
  committed via ``superuser_engine`` so ingestion tests have
  something to attach documents to.
- ``ingestion_app`` / ``ingestion_client`` — FastAPI app + TestClient
  with the memory auth adapter, in-memory store, null scanner.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from accounting_parser.api import create_app
from accounting_parser.auth.adapter import (
    AuthenticatedUser,
    AuthProvider,
    PasskeyCredential,
    UserRole,
)
from accounting_parser.auth.memory import (
    MemoryAuthAdapter,
    audience_for_tests,
    issuer_for_tests,
    kid_for_tests,
    signing_key_pem_for_tests,
)
from accounting_parser.config import Settings
from accounting_parser.ingestion.virus_scan import NullVirusScanner
from accounting_parser.storage.memory import InMemoryDocumentStoreAdapter


@dataclass(frozen=True)
class SeededFirm:
    tenant_id: UUID
    firm_id: UUID
    client_id: UUID
    engagement_id: UUID
    user_id: UUID


@pytest.fixture
def in_memory_store() -> InMemoryDocumentStoreAdapter:
    return InMemoryDocumentStoreAdapter()


@pytest.fixture
def null_scanner() -> NullVirusScanner:
    return NullVirusScanner()


@pytest.fixture
def ingestion_settings() -> Settings:
    """Test Settings — small max size for fast size-limit tests."""
    return Settings(
        db_url="postgresql+psycopg://unused-in-tests/unused",
        auth_adapter="authentik",
        authentik_audience=audience_for_tests(),
        authentik_issuer=issuer_for_tests(),
        authentik_api_token=SecretStr("test"),
        session_signing_key_pem=SecretStr(signing_key_pem_for_tests()),
        session_signing_kid=kid_for_tests(),
        session_duration_seconds=3600,
        magic_link_ttl_seconds=60,
        firm_rp_id="localhost",
        doc_store_adapter="memory",
        storage_bucket="test-bucket",
        ingest_max_bytes=1 * 1024 * 1024,  # 1 MB cap in tests
        virus_scanner="null",
    )


@pytest.fixture(autouse=True)
def _clean_ingestion_state(superuser_engine: Engine):
    """Wipe ingestion-related rows before every test.

    Ingestion has many cross-row constraints (engagement → client →
    firm → tenant). A per-test wipe keeps each test self-contained.
    """
    factory = sessionmaker(bind=superuser_engine, expire_on_commit=False)
    session = factory()
    try:
        # Child tables first. Audit log rows are wiped too so the
        # hash chain starts fresh per test.
        session.execute(text("DELETE FROM audit_log_entry"))
        session.execute(text("DELETE FROM document"))
        session.execute(text("DELETE FROM engagement"))
        session.execute(text("DELETE FROM webauthn_credential"))
        session.execute(text("DELETE FROM magic_link_token"))
        session.execute(text("DELETE FROM app_user"))
        session.execute(text("DELETE FROM client"))
        session.execute(text("DELETE FROM firm"))
        session.execute(text("DELETE FROM tenant"))
        session.commit()
    finally:
        session.close()
    yield


@pytest.fixture
def seeded_firm(superuser_engine: Engine) -> SeededFirm:
    """Insert a minimal firm/client/engagement/user for ingest tests."""
    factory = sessionmaker(bind=superuser_engine, expire_on_commit=False)
    session = factory()
    tenant_id = uuid4()
    firm_id = uuid4()
    client_id = uuid4()
    engagement_id = uuid4()
    user_id = uuid4()
    try:
        session.execute(
            text("INSERT INTO tenant (id, name) VALUES (:id, :n)"),
            {"id": str(tenant_id), "n": "Ingestion Tenant"},
        )
        session.execute(
            text("INSERT INTO firm (id, tenant_id, name) VALUES (:id, :tid, 'Firm')"),
            {"id": str(firm_id), "tid": str(tenant_id)},
        )
        session.execute(
            text(
                "INSERT INTO client (id, tenant_id, firm_id, name) "
                "VALUES (:id, :tid, :fid, 'Client Co')"
            ),
            {"id": str(client_id), "tid": str(tenant_id), "fid": str(firm_id)},
        )
        session.execute(
            text(
                """
                INSERT INTO engagement (id, tenant_id, client_id, name, engagement_type)
                VALUES (:id, :tid, :cid, 'Test Engagement', 'tax_return')
                """
            ),
            {"id": str(engagement_id), "tid": str(tenant_id), "cid": str(client_id)},
        )
        session.execute(
            text(
                """
                INSERT INTO app_user
                    (id, tenant_id, firm_id, cognito_sub, email, role)
                VALUES
                    (:id, :tid, :fid, :sub, :email, 'firm_administrator')
                """
            ),
            {
                "id": str(user_id),
                "tid": str(tenant_id),
                "fid": str(firm_id),
                "sub": f"memory-user-{user_id}",
                "email": "admin@firm.test",
            },
        )
        session.commit()
    finally:
        session.close()

    return SeededFirm(
        tenant_id=tenant_id,
        firm_id=firm_id,
        client_id=client_id,
        engagement_id=engagement_id,
        user_id=user_id,
    )


@pytest.fixture
def ingestion_memory_adapter() -> MemoryAuthAdapter:
    return MemoryAuthAdapter()


@pytest.fixture
def ingestion_app(
    ingestion_memory_adapter: MemoryAuthAdapter,
    ingestion_settings: Settings,
    app_engine: Engine,
    superuser_engine: Engine,
    in_memory_store: InMemoryDocumentStoreAdapter,
    null_scanner: NullVirusScanner,
):
    """FastAPI app with all ingestion dependencies injected."""
    app = create_app(
        settings=ingestion_settings,
        adapter=ingestion_memory_adapter,
        engine=app_engine,
        document_store=in_memory_store,
        virus_scanner=null_scanner,
    )
    app.state.platform_engine = superuser_engine
    app.state.platform_session_factory = sessionmaker(bind=superuser_engine, expire_on_commit=False)
    return app


@pytest.fixture
def ingestion_client(ingestion_app) -> Iterator[TestClient]:
    with TestClient(ingestion_app) as client:
        yield client


@pytest.fixture
def auth_token(ingestion_memory_adapter: MemoryAuthAdapter, seeded_firm: SeededFirm) -> str:
    """Mint a session token for the seeded Firm_Administrator.

    Synchronous wrapper; the memory adapter's issue_session is async.
    """
    import asyncio

    user = AuthenticatedUser(
        user_id=seeded_firm.user_id,
        tenant_id=seeded_firm.tenant_id,
        firm_id=seeded_firm.firm_id,
        email="admin@firm.test",
        role=UserRole.FIRM_ADMINISTRATOR,
        external_id=f"memory-user-{seeded_firm.user_id}",
        external_provider=AuthProvider.AUTHENTIK,
        session_expires_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        passkey_verified=True,
    )
    credential = PasskeyCredential(
        credential_id=b"test-cred", public_key=b"pk", sign_count=0, aaguid=None
    )
    token = asyncio.run(
        ingestion_memory_adapter.issue_session(
            user=user, credential=credential, session_duration_seconds=3600
        )
    )
    return token.token
