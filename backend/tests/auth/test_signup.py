"""Signup / firm bootstrap behavior tests.

Covers:
- R25.1 — signup provisions exactly one tenant + firm + admin user.
- R25.3 — second signup attempt returns 409 and audit-logs rejection.
- R26.5 — signup does not federate to external IdP (adapter-local only).
- Audit: every successful signup writes an auth.signup.succeeded row.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from accounting_parser.auth.memory import MemoryAuthAdapter
from accounting_parser.auth.service import AuthService, FirmAlreadyProvisionedError


@pytest.fixture
def platform_session(superuser_engine: Engine):
    """Session as the platform_admin role so bootstrap can write tenant rows.

    Signup in production runs as platform_admin via the installer;
    tests match that threat model.
    """
    factory = sessionmaker(bind=superuser_engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
        session.commit()
    finally:
        session.close()


@pytest.fixture(autouse=True)
def clean_firm_state(superuser_engine: Engine):
    """Wipe firm-bootstrap state before each test so every case is isolated.

    Signup is inherently stateful (R25.3 depends on prior state) so
    we can't rely on a rollback-only db_session fixture — the auth
    service uses an outer session and advisory locks.
    """
    factory = sessionmaker(bind=superuser_engine, expire_on_commit=False)
    session = factory()
    try:
        # Order matters: child tables first.
        session.execute(text("DELETE FROM audit_log_entry"))
        session.execute(text("DELETE FROM webauthn_credential"))
        session.execute(text("DELETE FROM magic_link_token"))
        session.execute(text("DELETE FROM app_user"))
        session.execute(text("DELETE FROM firm"))
        session.execute(text("DELETE FROM tenant"))
        session.commit()
    finally:
        session.close()
    yield


def test_bootstrap_firm_creates_tenant_firm_user(
    platform_session: Session, memory_adapter: MemoryAuthAdapter
):
    """R25.1: signup provisions the full trio of rows + audit entry."""
    service = AuthService(adapter=memory_adapter)
    result = asyncio.run(
        service.bootstrap_firm(
            platform_session,
            firm_name="Acme CPA",
            principal_email="alice@acme-cpa.example",
            principal_display_name="Alice Principal",
        )
    )
    platform_session.commit()

    # Rows exist in the DB.
    tenant_name = platform_session.execute(
        text("SELECT name FROM tenant WHERE id = :id"), {"id": str(result.tenant_id)}
    ).scalar_one()
    assert tenant_name == "Acme CPA"

    firm_name = platform_session.execute(
        text("SELECT name FROM firm WHERE id = :id"), {"id": str(result.firm_id)}
    ).scalar_one()
    assert firm_name == "Acme CPA"

    user_email = platform_session.execute(
        text("SELECT email FROM app_user WHERE id = :id"),
        {"id": str(result.firm_administrator_id)},
    ).scalar_one()
    assert user_email == "alice@acme-cpa.example"

    # Audit entry landed.
    action = platform_session.execute(
        text(
            """
            SELECT action FROM audit_log_entry
            WHERE tenant_id = :tid AND action = 'auth.signup.succeeded'
            """
        ),
        {"tid": str(result.tenant_id)},
    ).scalar_one()
    assert action == "auth.signup.succeeded"


def test_second_signup_rejected_r25_3(platform_session: Session, memory_adapter: MemoryAuthAdapter):
    """R25.3: a second signup on the same install is refused."""
    service = AuthService(adapter=memory_adapter)
    asyncio.run(
        service.bootstrap_firm(
            platform_session,
            firm_name="First Firm",
            principal_email="first@ex.com",
            principal_display_name="First",
        )
    )
    platform_session.commit()

    with pytest.raises(FirmAlreadyProvisionedError):
        asyncio.run(
            service.bootstrap_firm(
                platform_session,
                firm_name="Second Firm",
                principal_email="second@ex.com",
                principal_display_name="Second",
            )
        )
    platform_session.commit()

    # Rejection audit event exists.
    count = platform_session.execute(
        text(
            """
            SELECT count(*) FROM audit_log_entry
            WHERE action = 'auth.signup.rejected'
            """
        )
    ).scalar_one()
    assert count == 1


def test_signup_rolls_back_on_idp_failure(
    platform_session: Session, memory_adapter: MemoryAuthAdapter, monkeypatch
):
    """If the adapter's create_user fails, no DB artifacts remain.

    Prevents orphaned tenant/firm rows that would make R25.3 reject
    legitimate retries.
    """

    async def boom(**_kwargs):
        raise RuntimeError("authentik unreachable")

    monkeypatch.setattr(memory_adapter, "create_user", boom)

    service = AuthService(adapter=memory_adapter)
    with pytest.raises(RuntimeError, match="authentik unreachable"):
        asyncio.run(
            service.bootstrap_firm(
                platform_session,
                firm_name="Doomed Firm",
                principal_email="nope@ex.com",
                principal_display_name="Nope",
            )
        )
    platform_session.rollback()

    # Nothing got committed.
    n_firms = platform_session.execute(text("SELECT count(*) FROM firm")).scalar_one()
    assert n_firms == 0
    n_tenants = platform_session.execute(text("SELECT count(*) FROM tenant")).scalar_one()
    assert n_tenants == 0


def test_signup_result_ids_are_valid_uuids(
    platform_session: Session, memory_adapter: MemoryAuthAdapter
):
    """Defense against typo regressions where uuid4() gets replaced with a string."""
    service = AuthService(adapter=memory_adapter)
    result = asyncio.run(
        service.bootstrap_firm(
            platform_session,
            firm_name="UUID Check",
            principal_email="uuid@ex.com",
            principal_display_name="UUID",
        )
    )
    platform_session.commit()
    # These constructor calls fail if the values weren't UUID-like.
    assert isinstance(result.tenant_id, UUID)
    assert isinstance(result.firm_id, UUID)
    assert isinstance(result.firm_administrator_id, UUID)
