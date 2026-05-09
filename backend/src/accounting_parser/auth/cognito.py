"""Cognito auth adapter — stub for the cloud variant.

Purpose: confirm the ``AuthAdapter`` abstraction holds for both cloud
(Cognito) and self-hosted (Authentik) variants. Per the fork's task
P1.1, this file exists so:

1. The Protocol is exercised against two implementations (compile-
   time, via mypy's structural checks and the ``isinstance`` checks
   in tests).
2. When the cloud variant is re-instated later, the adapter shape is
   already committed — no refactor required.
3. No half-working "cloud-dev" surface ships with the self-hosted
   release; every method raises ``NotImplementedError`` with a
   pointer to the re-instatement plan.

The cloud variant is explicitly out-of-scope for the self-hosted fork
(README.md §Non-goals, Phase plan). If the spec changes and Cognito
becomes a first-class adapter again, fill this in with boto3-backed
logic.
"""

from __future__ import annotations

from uuid import UUID

from accounting_parser.auth.adapter import (
    AuthAdapter,
    AuthenticatedUser,
    AuthProvider,
    PasskeyCredential,
    SessionToken,
    UserRole,
)

_NOT_IMPLEMENTED_MSG = (
    "CognitoAuthAdapter is a stub in the self-hosted fork. "
    "The cloud variant is out of scope for this spec; see "
    ".kiro/specs/accounting-parser-self-hosted/README.md §Non-goals. "
    "If you reached this, either (a) AUTH_ADAPTER=cognito was set in "
    "configuration without re-instating the adapter, or (b) a test "
    "is exercising the Protocol shape against both implementations — "
    "which is the expected use of this stub."
)


class CognitoAuthAdapter(AuthAdapter):
    """Stub cloud adapter. Every operation raises NotImplementedError.

    The class exists at all so the Protocol has two concrete
    implementations and so type-checking catches drift between the
    two. No runtime branch should construct this adapter outside
    tests that assert "the stub refuses to do work."
    """

    provider: AuthProvider = AuthProvider.COGNITO

    def __init__(self, *, user_pool_id: str | None = None, region: str | None = None) -> None:
        # We accept the parent-spec config shape so the constructor
        # signature doesn't need a test-fixture change if the cloud
        # variant comes back. We just don't *do* anything with it.
        self.user_pool_id = user_pool_id
        self.region = region

    async def authenticate_request(self, raw_token: str) -> AuthenticatedUser | None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    async def create_user(
        self,
        *,
        tenant_id: UUID,
        firm_id: UUID,
        email: str,
        role: UserRole,
        display_name: str,
    ) -> str:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    async def enroll_passkey(
        self,
        *,
        external_id: str,
        credential: PasskeyCredential,
    ) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    async def issue_session(
        self,
        *,
        user: AuthenticatedUser,
        credential: PasskeyCredential,
        session_duration_seconds: int,
    ) -> SessionToken:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    async def verify_passkey_assertion(
        self,
        *,
        external_id: str,
        assertion: bytes,
        challenge: bytes,
        credential_id: bytes,
        public_key: bytes,
        stored_sign_count: int,
    ) -> int:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    async def invalidate_session(self, *, token: str) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)
