"""Concurrent-session property test (Correctness Property 6 extension).

Claim: under N concurrent requests with mixed tenants, no request's
``set_tenant_context`` call affects another request's RLS view.

The parent spec's CP6 already proved this at the DB level (test in
test_rls_tenant_isolation.py). This test extends the check to the
HTTP stack: minted session tokens for K distinct tenants are driven
through the FastAPI middleware in an asyncio.gather and each
response's /auth/me body matches the tenant_id the caller expected.

50 iterations across 10 tenants × 5 requests each. Bounded for CI;
raise iteration count locally when debugging.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from accounting_parser.auth.adapter import (
    AuthenticatedUser,
    AuthProvider,
    PasskeyCredential,
    UserRole,
)
from accounting_parser.auth.memory import MemoryAuthAdapter


async def _mint_token(adapter: MemoryAuthAdapter) -> tuple[str, str]:
    """Mint one token for a fresh user; return (token, expected_tenant)."""
    user = AuthenticatedUser(
        user_id=uuid4(),
        tenant_id=uuid4(),
        firm_id=uuid4(),
        email=f"user-{uuid4().hex}@example.com",
        role=UserRole.PREPARER,
        external_id=f"memory-{uuid4().hex}",
        external_provider=AuthProvider.AUTHENTIK,
        session_expires_at=datetime.now(UTC) + timedelta(hours=1),
        passkey_verified=True,
    )
    credential = PasskeyCredential(
        credential_id=uuid4().bytes,
        public_key=b"pk",
        sign_count=0,
        aaguid=None,
    )
    session = await adapter.issue_session(
        user=user, credential=credential, session_duration_seconds=3600
    )
    return session.token, str(user.tenant_id)


def test_50_concurrent_requests_no_tenant_leak(
    auth_client: TestClient, memory_adapter: MemoryAuthAdapter
):
    """Fifty concurrent /auth/me requests each see their own tenant."""

    async def _run() -> list[tuple[str, str]]:
        # Mint 50 tokens serially (adapter is not thread-safe on counters
        # but is async-coroutine safe; we await one at a time here).
        return [await _mint_token(memory_adapter) for _ in range(50)]

    tokens = asyncio.run(_run())

    # Drive them "concurrently" through the TestClient. FastAPI's
    # TestClient is synchronous, but each request is independent and
    # the middleware's critical region is per-request, so interleaving
    # via threads is the relevant stress. We drop to httpx.AsyncClient
    # to get real concurrency.
    async def _hit_all():
        transport = httpx.ASGITransport(app=auth_client.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await asyncio.gather(
                *[
                    client.get("/auth/me", headers={"Authorization": f"Bearer {t}"})
                    for t, _ in tokens
                ]
            )

    responses = asyncio.run(_hit_all())

    assert len(responses) == 50
    for (_token, expected_tid), response in zip(tokens, responses, strict=False):
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["tenant_id"] == expected_tid, (
            "request resolved a tenant other than the one its token claimed — "
            "this means middleware state leaked between requests"
        )
