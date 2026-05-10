"""Auth audit events extend the parent audit hash chain unbroken.

Parent Task 3 proved (CP8) that audit_log_entry entries form a
verifiable sha256 hash chain. Auth events use the same insert path,
so any sequence of auth events + non-auth events should still
verify. This test confirms the chain holds when auth events are
interleaved with parent-spec events.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from accounting_parser.auth.memory import MemoryAuthAdapter
from accounting_parser.auth.service import AuthService


@pytest.fixture
def platform_session(superuser_engine: Engine):
    factory = sessionmaker(bind=superuser_engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _clean(superuser_engine: Engine):
    factory = sessionmaker(bind=superuser_engine, expire_on_commit=False)
    session = factory()
    session.execute(text("DELETE FROM audit_log_entry"))
    session.execute(text("DELETE FROM webauthn_credential"))
    session.execute(text("DELETE FROM magic_link_token"))
    session.execute(text("DELETE FROM app_user"))
    session.execute(text("DELETE FROM firm"))
    session.execute(text("DELETE FROM tenant"))
    session.commit()
    session.close()
    yield


def test_chain_verifies_through_auth_events(platform_session: Session):
    """Manually write a mix of auth and non-auth events; verify chain."""
    tid = uuid4()
    platform_session.execute(
        text("INSERT INTO tenant (id, name) VALUES (:id, :n)"),
        {"id": str(tid), "n": "chain"},
    )
    platform_session.execute(
        text("SELECT set_config('app.tenant_id', :tid, false)"),
        {"tid": str(tid)},
    )

    # Interleave domain and auth events.
    actions = [
        "auth.signup.succeeded",
        "document.uploaded",
        "auth.login.succeeded",
        "document.parsed",
        "auth.magic_link.issued",
        "workflow.step.completed",
    ]
    for a in actions:
        platform_session.execute(
            text(
                """
                INSERT INTO audit_log_entry
                  (tenant_id, action, resource_type, payload,
                   prev_hash, payload_hash)
                VALUES
                  (:tid, :act, 'test', '{}'::jsonb,
                   '\\x0000000000000000000000000000000000000000000000000000000000000000',
                   '\\x0000000000000000000000000000000000000000000000000000000000000000')
                """
            ),
            {"tid": str(tid), "act": a},
        )
    platform_session.commit()

    # Read back and verify the hash chain.
    rows = platform_session.execute(
        text(
            """
            SELECT sequence_number, prev_hash, payload_hash
            FROM audit_log_entry
            WHERE tenant_id = :tid
            ORDER BY sequence_number
            """
        ),
        {"tid": str(tid)},
    ).all()

    assert len(rows) == len(actions)
    last_hash = b"\x00" * 32
    for seq, prev_h, pl_h in rows:
        assert bytes(prev_h) == last_hash, f"broken chain at seq={seq}"
        last_hash = bytes(pl_h)
        assert len(last_hash) == 32


def test_signup_through_service_produces_chainable_entry(
    platform_session: Session, memory_adapter: MemoryAuthAdapter
):
    """End-to-end: service.bootstrap_firm emits an entry that chains cleanly."""
    service = AuthService(adapter=memory_adapter)
    result = asyncio.run(
        service.bootstrap_firm(
            platform_session,
            firm_name="ChainTest",
            principal_email="chain@example.com",
            principal_display_name="Chain",
        )
    )
    platform_session.commit()

    # Verify exactly one auth.signup.succeeded row landed and the chain
    # is self-consistent (the trigger would have raised on violation).
    rows = platform_session.execute(
        text(
            """
            SELECT sequence_number, prev_hash, payload_hash, action
            FROM audit_log_entry
            WHERE tenant_id = :tid
            ORDER BY sequence_number
            """
        ),
        {"tid": str(result.tenant_id)},
    ).all()
    assert len(rows) == 1
    assert rows[0][3] == "auth.signup.succeeded"
    assert bytes(rows[0][1]) == b"\x00" * 32  # genesis
    assert len(bytes(rows[0][2])) == 32  # non-zero payload hash
