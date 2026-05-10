"""Workflow test fixtures."""

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
from accounting_parser.workflow.registry import StepRegistry


@dataclass(frozen=True)
class SeededEngagement:
    tenant_id: UUID
    firm_id: UUID
    client_id: UUID
    engagement_id: UUID
    preparer_id: UUID
    reviewer_id: UUID


@pytest.fixture(autouse=True)
def _clean_workflow_state(superuser_engine: Engine):
    factory = sessionmaker(bind=superuser_engine, expire_on_commit=False)
    session = factory()
    try:
        session.execute(text("DELETE FROM audit_log_entry"))
        session.execute(text("DELETE FROM workflow_step_run"))
        session.execute(text("DELETE FROM workflow_run"))
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
def seeded_engagement(superuser_engine: Engine) -> SeededEngagement:
    factory = sessionmaker(bind=superuser_engine, expire_on_commit=False)
    session = factory()
    tenant_id = uuid4()
    firm_id = uuid4()
    client_id = uuid4()
    engagement_id = uuid4()
    preparer_id = uuid4()
    reviewer_id = uuid4()
    try:
        session.execute(
            text("INSERT INTO tenant (id, name) VALUES (:id, :n)"),
            {"id": str(tenant_id), "n": "Workflow Tenant"},
        )
        session.execute(
            text("INSERT INTO firm (id, tenant_id, name) VALUES (:id, :tid, 'Firm')"),
            {"id": str(firm_id), "tid": str(tenant_id)},
        )
        session.execute(
            text(
                "INSERT INTO client (id, tenant_id, firm_id, name) "
                "VALUES (:id, :tid, :fid, 'Client')"
            ),
            {"id": str(client_id), "tid": str(tenant_id), "fid": str(firm_id)},
        )
        session.execute(
            text(
                """
                INSERT INTO engagement (id, tenant_id, client_id, name, engagement_type)
                VALUES (:id, :tid, :cid, 'Monthly Close', 'bookkeeping')
                """
            ),
            {"id": str(engagement_id), "tid": str(tenant_id), "cid": str(client_id)},
        )
        for uid, role, email in [
            (preparer_id, "preparer", "prep@firm.test"),
            (reviewer_id, "reviewer", "rev@firm.test"),
        ]:
            session.execute(
                text(
                    """
                    INSERT INTO app_user
                        (id, tenant_id, firm_id, cognito_sub, email, role)
                    VALUES (:id, :tid, :fid, :sub, :email, :role)
                    """
                ),
                {
                    "id": str(uid),
                    "tid": str(tenant_id),
                    "fid": str(firm_id),
                    "sub": f"memory-user-{uid}",
                    "email": email,
                    "role": role,
                },
            )
        session.commit()
    finally:
        session.close()
    return SeededEngagement(
        tenant_id=tenant_id,
        firm_id=firm_id,
        client_id=client_id,
        engagement_id=engagement_id,
        preparer_id=preparer_id,
        reviewer_id=reviewer_id,
    )


@pytest.fixture
def workflow_registry() -> StepRegistry:
    reg = StepRegistry()
    reg.register_builtin_stubs()
    return reg


@pytest.fixture
def workflow_memory_adapter() -> MemoryAuthAdapter:
    return MemoryAuthAdapter()


@pytest.fixture
def workflow_settings() -> Settings:
    return Settings(
        db_url="postgresql+psycopg://unused/unused",
        auth_adapter="authentik",
        authentik_audience=audience_for_tests(),
        authentik_issuer=issuer_for_tests(),
        authentik_api_token=SecretStr("test"),
        session_signing_key_pem=SecretStr(signing_key_pem_for_tests()),
        session_signing_kid=kid_for_tests(),
        session_duration_seconds=3600,
        doc_store_adapter="memory",
        virus_scanner="null",
        firm_rp_id="localhost",
    )


@pytest.fixture
def workflow_app(
    workflow_memory_adapter: MemoryAuthAdapter,
    workflow_settings: Settings,
    workflow_registry: StepRegistry,
    app_engine: Engine,
    superuser_engine: Engine,
):
    app = create_app(
        settings=workflow_settings,
        adapter=workflow_memory_adapter,
        engine=app_engine,
        document_store=InMemoryDocumentStoreAdapter(),
        virus_scanner=NullVirusScanner(),
        workflow_registry=workflow_registry,
    )
    app.state.platform_engine = superuser_engine
    app.state.platform_session_factory = sessionmaker(bind=superuser_engine, expire_on_commit=False)
    return app


@pytest.fixture
def workflow_client(workflow_app) -> Iterator[TestClient]:
    with TestClient(workflow_app) as client:
        yield client


def _mint(
    adapter: MemoryAuthAdapter,
    *,
    user_id: UUID,
    tenant_id: UUID,
    firm_id: UUID,
    role: str,
    email: str,
) -> str:
    import asyncio
    from datetime import UTC, datetime

    user = AuthenticatedUser(
        user_id=user_id,
        tenant_id=tenant_id,
        firm_id=firm_id,
        email=email,
        role=UserRole(role),
        external_id=f"memory-user-{user_id}",
        external_provider=AuthProvider.AUTHENTIK,
        session_expires_at=datetime.now(UTC),
        passkey_verified=True,
    )
    cred = PasskeyCredential(credential_id=b"c", public_key=b"p", sign_count=0, aaguid=None)
    tok = asyncio.run(
        adapter.issue_session(user=user, credential=cred, session_duration_seconds=3600)
    )
    return tok.token


@pytest.fixture
def preparer_token(
    workflow_memory_adapter: MemoryAuthAdapter, seeded_engagement: SeededEngagement
) -> str:
    return _mint(
        workflow_memory_adapter,
        user_id=seeded_engagement.preparer_id,
        tenant_id=seeded_engagement.tenant_id,
        firm_id=seeded_engagement.firm_id,
        role="preparer",
        email="prep@firm.test",
    )


@pytest.fixture
def reviewer_token(
    workflow_memory_adapter: MemoryAuthAdapter, seeded_engagement: SeededEngagement
) -> str:
    return _mint(
        workflow_memory_adapter,
        user_id=seeded_engagement.reviewer_id,
        tenant_id=seeded_engagement.tenant_id,
        firm_id=seeded_engagement.firm_id,
        role="reviewer",
        email="rev@firm.test",
    )
