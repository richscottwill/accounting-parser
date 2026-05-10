"""Magic-link auth tests (R26.4).

Covers:
- Issue stores a sha256, not the raw token.
- Consume marks the row used and returns tenant+email.
- Second consume of the same token is rejected.
- Expired tokens are rejected uniformly.
- Audit entries land for issue + consume + reject paths.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from accounting_parser.auth.memory import MemoryAuthAdapter
from accounting_parser.auth.service import AuthService, InvalidMagicLinkError


@pytest.fixture
def platform_session(superuser_engine: Engine):
    factory = sessionmaker(bind=superuser_engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def seeded_tenant(platform_session: Session):
    """Insert a tenant so magic-link tests have something to scope to."""
    platform_session.execute(text("DELETE FROM magic_link_token"))
    platform_session.execute(text("DELETE FROM audit_log_entry"))
    platform_session.execute(text("DELETE FROM webauthn_credential"))
    platform_session.execute(text("DELETE FROM app_user"))
    platform_session.execute(text("DELETE FROM firm"))
    platform_session.execute(text("DELETE FROM tenant"))
    tid = uuid4()
    platform_session.execute(
        text("INSERT INTO tenant (id, name) VALUES (:id, :name)"),
        {"id": str(tid), "name": "Magic Link Tenant"},
    )
    platform_session.commit()
    return tid


def test_issue_persists_hash_not_raw(
    platform_session: Session, memory_adapter: MemoryAuthAdapter, seeded_tenant
):
    """Raw token never reaches the DB; only sha256 is stored."""
    service = AuthService(adapter=memory_adapter)
    issued = asyncio.run(
        service.issue_magic_link(
            platform_session,
            tenant_id=seeded_tenant,
            email="client@example.com",
        )
    )
    platform_session.commit()

    # Raw token is returned once.
    assert issued.raw_token
    assert isinstance(issued.token_hash, bytes)
    assert len(issued.token_hash) == 32

    # DB row has the hash, not the raw.
    stored_hash = platform_session.execute(
        text("SELECT token_hash FROM magic_link_token WHERE tenant_id = :tid"),
        {"tid": str(seeded_tenant)},
    ).scalar_one()
    assert bytes(stored_hash) == issued.token_hash


def test_consume_returns_tenant_and_email(
    platform_session: Session, memory_adapter: MemoryAuthAdapter, seeded_tenant
):
    service = AuthService(adapter=memory_adapter)
    issued = asyncio.run(
        service.issue_magic_link(
            platform_session,
            tenant_id=seeded_tenant,
            email="client@example.com",
        )
    )
    platform_session.commit()

    tid, email = asyncio.run(
        service.consume_magic_link(platform_session, raw_token=issued.raw_token)
    )
    platform_session.commit()
    assert tid == seeded_tenant
    assert email == "client@example.com"


def test_second_consume_rejected(
    platform_session: Session, memory_adapter: MemoryAuthAdapter, seeded_tenant
):
    """Single-use enforcement: second consume of the same token is rejected."""
    service = AuthService(adapter=memory_adapter)
    issued = asyncio.run(
        service.issue_magic_link(
            platform_session,
            tenant_id=seeded_tenant,
            email="c@example.com",
        )
    )
    platform_session.commit()

    asyncio.run(service.consume_magic_link(platform_session, raw_token=issued.raw_token))
    platform_session.commit()

    with pytest.raises(InvalidMagicLinkError):
        asyncio.run(service.consume_magic_link(platform_session, raw_token=issued.raw_token))
    platform_session.rollback()


def test_expired_token_rejected(
    platform_session: Session, memory_adapter: MemoryAuthAdapter, seeded_tenant
):
    """A token past its expires_at is rejected uniformly."""
    service = AuthService(adapter=memory_adapter)
    issued = asyncio.run(
        service.issue_magic_link(
            platform_session,
            tenant_id=seeded_tenant,
            email="expired@example.com",
        )
    )
    # Force-age the token by updating expires_at into the past.
    platform_session.execute(
        text("UPDATE magic_link_token SET expires_at = :e WHERE token_hash = :h"),
        {
            "e": datetime.now(UTC) - timedelta(seconds=1),
            "h": issued.token_hash,
        },
    )
    platform_session.commit()

    with pytest.raises(InvalidMagicLinkError):
        asyncio.run(service.consume_magic_link(platform_session, raw_token=issued.raw_token))
    platform_session.rollback()


def test_unknown_token_rejected_with_same_error(
    platform_session: Session, memory_adapter: MemoryAuthAdapter, seeded_tenant
):
    """Unknown and expired tokens share the same exception type (anti-oracle)."""
    service = AuthService(adapter=memory_adapter)
    with pytest.raises(InvalidMagicLinkError):
        asyncio.run(service.consume_magic_link(platform_session, raw_token="not-a-real-token"))
    platform_session.rollback()


def test_audit_entries_cover_all_paths(
    platform_session: Session, memory_adapter: MemoryAuthAdapter, seeded_tenant
):
    service = AuthService(adapter=memory_adapter)
    issued = asyncio.run(
        service.issue_magic_link(
            platform_session,
            tenant_id=seeded_tenant,
            email="audit@example.com",
        )
    )
    platform_session.commit()

    asyncio.run(service.consume_magic_link(platform_session, raw_token=issued.raw_token))
    platform_session.commit()

    with pytest.raises(InvalidMagicLinkError):
        asyncio.run(service.consume_magic_link(platform_session, raw_token="bogus"))
    platform_session.rollback()

    actions = set(
        platform_session.execute(
            text(
                """
                SELECT DISTINCT action FROM audit_log_entry
                WHERE tenant_id = :tid
                """
            ),
            {"tid": str(seeded_tenant)},
        ).scalars()
    )
    assert "auth.magic_link.issued" in actions
    assert "auth.magic_link.consumed" in actions
    assert "auth.magic_link.rejected" in actions
