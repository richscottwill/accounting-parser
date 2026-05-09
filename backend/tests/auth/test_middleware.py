"""AuthMiddleware tests.

Covers:
- Allow-listed paths go through without a token.
- Missing / malformed / expired tokens return 401 with generic body.
- Valid tokens attach an ``AuthenticatedUser`` to request.state.
- /auth/me reflects the token's claims.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from jose import jwt

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


def test_allow_list_health_no_token(auth_client: TestClient):
    """Liveness probe never requires auth."""
    response = auth_client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_missing_token_unauthorized(auth_client: TestClient):
    """Any protected path without a token returns 401."""
    response = auth_client.get("/auth/me")
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_invalid_token_unauthorized(auth_client: TestClient):
    """Malformed bearer token returns 401 with generic body."""
    response = auth_client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-jwt"})
    assert response.status_code == 401


def test_valid_token_me_reflects_claims(auth_client: TestClient, memory_adapter: MemoryAuthAdapter):
    """A token issued by the adapter verifies and /auth/me reflects the user."""
    # Manually mint a session via the memory adapter.
    user = AuthenticatedUser(
        user_id=uuid4(),
        tenant_id=uuid4(),
        firm_id=uuid4(),
        email="me@example.com",
        role=UserRole.FIRM_ADMINISTRATOR,
        external_id="memory-user-1",
        external_provider=AuthProvider.AUTHENTIK,
        session_expires_at=datetime.now(UTC) + timedelta(hours=1),
        passkey_verified=True,
    )
    credential = PasskeyCredential(
        credential_id=b"test-cred-id",
        public_key=b"test-pk",
        sign_count=0,
        aaguid=None,
    )
    token = asyncio.run(
        memory_adapter.issue_session(
            user=user, credential=credential, session_duration_seconds=3600
        )
    )
    response = auth_client.get("/auth/me", headers={"Authorization": f"Bearer {token.token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == str(user.user_id)
    assert body["tenant_id"] == str(user.tenant_id)
    assert body["email"] == "me@example.com"
    assert body["role"] == "firm_administrator"


def test_expired_token_rejected(auth_client: TestClient, memory_adapter: MemoryAuthAdapter):
    """A token whose exp is in the past returns 401."""
    past = datetime.now(UTC) - timedelta(hours=1)
    past_ts = int(past.timestamp())
    # Mint manually with a past exp.
    claims = {
        "iss": issuer_for_tests(),
        "aud": audience_for_tests(),
        "sub": "memory-user-expired",
        "uid": str(uuid4()),
        "tid": str(uuid4()),
        "fid": None,
        "email": "expired@example.com",
        "role": "preparer",
        "credhash": "AAAA",
        "iat": past_ts - 3600,
        "exp": past_ts,
        "jti": "expired-jti",
    }
    token = jwt.encode(
        claims,
        signing_key_pem_for_tests(),
        algorithm="RS256",
        headers={"kid": kid_for_tests()},
    )
    response = auth_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_signup_endpoint_is_allow_listed(auth_client: TestClient):
    """Signup must be reachable without a token (it runs before any user exists)."""
    # We don't complete the flow here (separate test); we only assert
    # that the middleware doesn't block the path.
    response = auth_client.post(
        "/auth/signup",
        json={
            "firm_name": "Allowlist Firm",
            "principal_email": "allow@example.com",
            "principal_display_name": "Allow User",
        },
    )
    # 201 (clean signup) or 409 (previous test left state) or 400 — any
    # non-401 proves the middleware let us in. We tolerate 201/409 here
    # because ordering with other tests is not fixed.
    assert response.status_code != 401
