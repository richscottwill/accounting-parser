"""AuthAdapter Protocol and its data-transfer objects.

This module defines the contract that every authentication backend
implements. The rest of the system depends only on this Protocol and
the DTOs below; it never imports Authentik, Cognito, or any other
vendor-specific client.

Design contract (self-hosted fork design.md §1):

- Adapter contracts stay at the parent layer; only transports change.
- Every adapter supports the same operations (authenticate_request,
  create_user, enroll_passkey, issue_session, verify_session).
- Per-Tenant isolation is enforced by the DB layer (RLS); adapters
  surface which tenant_id a session belongs to so the middleware can
  pin it on the DB session before any query runs.

Design contract (requirements.md R26):

- Passkey-first signup is required for Firm_Administrator and any
  user whose ``passkey_required`` flag is true (default: true).
- Password fallback is off by default; firm-level opt-in enables
  password + TOTP for specific users.
- Session tokens are bound to the issuing device's public key
  credential (R26.3).
- Client portal (R26.4) uses magic-link + passkey on first login,
  not password auth at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol
from uuid import UUID


class UserRole(str, Enum):
    """Roles aligned with the ``app_user.role`` CHECK constraint in schema."""

    FIRM_ADMINISTRATOR = "firm_administrator"
    PREPARER = "preparer"
    REVIEWER = "reviewer"
    CLIENT_PORTAL = "client_portal"


class AuthProvider(str, Enum):
    """Which identity provider issued a given ``external_id``."""

    AUTHENTIK = "authentik"
    COGNITO = "cognito"


@dataclass(frozen=True)
class AuthenticatedUser:
    """The resolved principal for a request.

    Produced by ``AuthAdapter.authenticate_request``; consumed by the
    middleware to call ``set_tenant_context`` and to populate the
    request-scoped ``current_user`` dependency.

    Immutable — mutation would allow a request handler to silently
    escalate privilege after middleware pinned the tenant.
    """

    user_id: UUID
    tenant_id: UUID
    firm_id: UUID | None
    email: str
    role: UserRole
    external_id: str
    external_provider: AuthProvider
    session_expires_at: datetime
    passkey_verified: bool


@dataclass(frozen=True)
class PasskeyCredential:
    """A FIDO2 / WebAuthn credential associated with an ``app_user``.

    Stored in the ``webauthn_credential`` table (added in migration 0002).
    The credential_id and public_key are opaque to us — fido2 handles
    the cryptography; we only persist what the library hands back.
    """

    credential_id: bytes
    public_key: bytes
    sign_count: int
    aaguid: bytes | None
    transports: tuple[str, ...] = ()


@dataclass(frozen=True)
class SessionToken:
    """A JWT-like session token bundle.

    The raw JWT is carried in ``token``; ``expires_at`` mirrors the
    JWT ``exp`` claim for convenience. ``credential_id_hash`` is
    included so the middleware can verify R26.3 session-binding:
    the session is valid only when re-presented by the same device
    whose passkey produced it.
    """

    token: str
    expires_at: datetime
    user_id: UUID
    credential_id_hash: bytes  # sha256 of the passkey credential id
    issued_at: datetime


@dataclass
class SignupRequest:
    """The inputs the installer passes to AuthService.bootstrap_firm.

    Separated from AuthAdapter so the adapter never has to carry
    single-firm-check logic (that lives in AuthService per R25.3).
    """

    firm_name: str
    principal_email: str
    principal_display_name: str
    tenant_name: str | None = None  # defaults to firm_name for single-firm installs
    # Supplied by the installer; the adapter never generates this client-side.
    ip_address: str | None = None
    user_agent: str | None = None
    # Runtime-only fields for audit; never persisted.
    metadata: dict[str, str] = field(default_factory=dict)


class AuthAdapter(Protocol):
    """The identity-provider contract.

    Implementations: ``AuthentikAuthAdapter`` (self-hosted default),
    ``CognitoAuthAdapter`` (cloud-variant, currently a stub).

    All methods are pure functions over the adapter's own state — they
    MUST NOT touch the application database directly. Persistence of
    ``app_user`` rows, ``webauthn_credential`` rows, and audit events
    happens in ``AuthService``; adapters only talk to their IdP.
    """

    provider: AuthProvider

    async def authenticate_request(self, raw_token: str) -> AuthenticatedUser | None:
        """Verify a session token and return the resolved principal.

        Returns None for any verification failure (missing, expired,
        malformed, signature mismatch, revoked). Never raises on
        invalid input — the middleware turns None into a 401. Raising
        would leak adapter-internal error taxonomy.
        """
        ...

    async def create_user(
        self,
        *,
        tenant_id: UUID,
        firm_id: UUID,
        email: str,
        role: UserRole,
        display_name: str,
    ) -> str:
        """Provision a user at the IdP and return its external_id.

        The returned external_id is what the application stores in
        ``app_user.external_id``. The adapter handles any provider-
        specific user-pool routing (e.g., Authentik preparer group
        vs. client-portal group).
        """
        ...

    async def enroll_passkey(
        self,
        *,
        external_id: str,
        credential: PasskeyCredential,
    ) -> None:
        """Register a WebAuthn credential for the user at the IdP.

        The credential has already been verified by fido2 at the
        application layer; the adapter's job is to notify the IdP so
        it knows the user now has a passkey (some IdPs track this
        for their own UX; Authentik specifically supports it).
        """
        ...

    async def issue_session(
        self,
        *,
        user: AuthenticatedUser,
        credential: PasskeyCredential,
        session_duration_seconds: int,
    ) -> SessionToken:
        """Mint a session token bound to the given passkey credential.

        The session MUST encode ``tenant_id`` so the middleware can
        pin RLS context without a DB lookup on every request. The
        credential's identity is hashed into the token so R26.3
        (session binding) can be verified on each subsequent request.
        """
        ...

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
        """Verify a WebAuthn assertion, returning the new sign_count.

        On verification success, the caller stores the new sign_count
        in ``webauthn_credential``. On failure, the adapter raises
        ``PasskeyAssertionError``; callers treat this as a log-and-reject.
        """
        ...

    async def invalidate_session(self, *, token: str) -> None:
        """Revoke a session at the IdP.

        Best-effort; some IdPs (stateless JWT setups) cannot truly
        revoke mid-flight. Authentik supports token revocation.
        Called on logout and on session timeout.
        """
        ...


class PasskeyAssertionError(RuntimeError):
    """Raised when a WebAuthn assertion fails verification.

    Middleware and routes should catch this and return a generic
    401 — do NOT surface the specific cryptographic reason to
    clients, to avoid leaking oracles for credential stuffing.
    """


class SessionVerificationError(RuntimeError):
    """Raised when a session token is malformed at the structural level.

    Distinct from ``authenticate_request`` returning None (which
    covers cryptographic / expiry failures). Structural errors
    indicate a bug or a pathological client; middleware logs them
    with redacted context rather than returning a standard 401.
    """
