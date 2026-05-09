"""AuthAdapter Protocol — structural + behavioral checks.

These tests confirm the adapter abstraction holds for both the
self-hosted default (Authentik, instantiated from config) and the
cloud stub (Cognito, always-raises). Without them, a future refactor
could drift one adapter from the Protocol and production would only
catch it at runtime.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from accounting_parser.auth.adapter import AuthProvider, PasskeyCredential, UserRole
from accounting_parser.auth.authentik import AuthentikAuthAdapter, AuthentikConfig
from accounting_parser.auth.cognito import CognitoAuthAdapter
from accounting_parser.auth.memory import MemoryAuthAdapter


def _make_authentik() -> AuthentikAuthAdapter:
    return AuthentikAuthAdapter(
        AuthentikConfig(
            base_url="http://authentik.test",
            client_id="test",
            api_token="test-token",
            jwks_url="http://authentik.test/jwks",
            audience="test-aud",
            issuer="http://authentik.test/iss",
            session_signing_key=(
                "-----BEGIN PRIVATE KEY-----\n"
                "MC4CAQAwBQYDK2VwBCIEIBSdRZ7CFI/N+2pdkKVfVYfkHuUGkdPcJRfzR9vi5/j8\n"
                "-----END PRIVATE KEY-----\n"
            ),
            session_signing_kid="test-kid",
        )
    )


@pytest.mark.parametrize(
    "adapter_factory",
    [
        lambda: MemoryAuthAdapter(),
        _make_authentik,
        lambda: CognitoAuthAdapter(),
    ],
)
def test_adapter_conforms_to_protocol(adapter_factory):
    """Every adapter must satisfy the AuthAdapter structural contract."""
    adapter = adapter_factory()
    # Protocol conformance via isinstance check (Protocol is runtime
    # checkable in 3.12 when decorated; ours isn't — so we check
    # attributes individually).
    for attr in (
        "provider",
        "authenticate_request",
        "create_user",
        "enroll_passkey",
        "issue_session",
        "verify_passkey_assertion",
        "invalidate_session",
    ):
        assert hasattr(adapter, attr), f"{type(adapter).__name__} missing {attr}"


def test_cognito_adapter_is_a_stub():
    """Every Cognito adapter method raises NotImplementedError.

    This is the contract that keeps the cloud-variant stub from
    silently doing the wrong thing in production.
    """
    adapter = CognitoAuthAdapter()
    assert adapter.provider is AuthProvider.COGNITO

    import asyncio

    async def drive() -> None:
        with pytest.raises(NotImplementedError):
            await adapter.authenticate_request("token")
        with pytest.raises(NotImplementedError):
            await adapter.create_user(
                tenant_id=uuid4(),
                firm_id=uuid4(),
                email="test@example.com",
                role=UserRole.PREPARER,
                display_name="T",
            )
        with pytest.raises(NotImplementedError):
            await adapter.enroll_passkey(
                external_id="x",
                credential=PasskeyCredential(
                    credential_id=b"c", public_key=b"p", sign_count=0, aaguid=None
                ),
            )
        with pytest.raises(NotImplementedError):
            await adapter.invalidate_session(token="t")

    asyncio.run(drive())


def test_authentik_adapter_is_self_hosted_provider():
    """AuthentikAuthAdapter reports the right provider tag."""
    adapter = _make_authentik()
    assert adapter.provider is AuthProvider.AUTHENTIK


def test_memory_adapter_reports_authentik_provider():
    """Memory adapter masquerades as authentik so service-layer behavior matches.

    Rationale: the adapter is used in tests that exercise code paths
    expecting ``AuthProvider.AUTHENTIK``. Using a distinct "memory"
    tag would have tests pass while production-like code (matching
    on provider) would fail.
    """
    adapter = MemoryAuthAdapter()
    assert adapter.provider is AuthProvider.AUTHENTIK
