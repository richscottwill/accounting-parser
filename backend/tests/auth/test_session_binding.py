"""R26.3 session-binding checks.

The session JWT encodes ``credhash`` = sha256(credential_id). Any
verifier (middleware or downstream logic) must treat this as the
binding between the session and the physical passkey that issued it.

At P1.1 we bind the claim into the token; actual "reject if claim
doesn't match presented credential" enforcement lives where the
credential is presented again (e.g., step-up auth endpoints in
Phase 2). These tests pin the P1.1 contract: the token carries the
binding, it's stable, and it's derivable from the credential.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

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
    signing_key_pem_for_tests,
)


def _make_user() -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=uuid4(),
        tenant_id=uuid4(),
        firm_id=uuid4(),
        email="binding@example.com",
        role=UserRole.PREPARER,
        external_id=f"memory-{uuid4().hex}",
        external_provider=AuthProvider.AUTHENTIK,
        session_expires_at=datetime.now(UTC) + timedelta(hours=1),
        passkey_verified=True,
    )


def test_token_credhash_matches_credential_id_hash():
    """The minted token's ``credhash`` claim equals sha256(credential_id)."""
    adapter = MemoryAuthAdapter()
    user = _make_user()
    credential = PasskeyCredential(
        credential_id=b"deadbeef-credential",
        public_key=b"pk",
        sign_count=0,
        aaguid=None,
    )
    token = asyncio.run(
        adapter.issue_session(user=user, credential=credential, session_duration_seconds=3600)
    )

    # Decode without verify is fine here — we're inspecting, not trusting.
    import base64

    claims = jwt.decode(
        token.token,
        _public_pem_from_private(signing_key_pem_for_tests()),
        algorithms=["RS256"],
        audience=audience_for_tests(),
        issuer=issuer_for_tests(),
    )
    observed = base64.urlsafe_b64decode(claims["credhash"] + "=" * (-len(claims["credhash"]) % 4))
    expected = hashlib.sha256(credential.credential_id).digest()
    assert observed == expected


def _public_pem_from_private(pem: str) -> str:
    from cryptography.hazmat.primitives import serialization

    priv = serialization.load_pem_private_key(pem.encode(), password=None)
    return (
        priv.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )


def test_token_credhash_is_stable_across_calls():
    """Minting twice with the same credential yields identical credhash claims."""
    adapter = MemoryAuthAdapter()
    user = _make_user()
    credential = PasskeyCredential(
        credential_id=b"same-cred-id",
        public_key=b"pk",
        sign_count=0,
        aaguid=None,
    )
    t1 = asyncio.run(
        adapter.issue_session(user=user, credential=credential, session_duration_seconds=3600)
    )
    t2 = asyncio.run(
        adapter.issue_session(user=user, credential=credential, session_duration_seconds=3600)
    )
    assert t1.credential_id_hash == t2.credential_id_hash
    # JTIs differ (different sessions), but credhashes match.
    assert t1.token != t2.token


def test_different_credentials_produce_different_credhashes():
    adapter = MemoryAuthAdapter()
    user = _make_user()
    c1 = PasskeyCredential(credential_id=b"cred-a", public_key=b"p", sign_count=0, aaguid=None)
    c2 = PasskeyCredential(credential_id=b"cred-b", public_key=b"p", sign_count=0, aaguid=None)
    t1 = asyncio.run(adapter.issue_session(user=user, credential=c1, session_duration_seconds=3600))
    t2 = asyncio.run(adapter.issue_session(user=user, credential=c2, session_duration_seconds=3600))
    assert t1.credential_id_hash != t2.credential_id_hash
