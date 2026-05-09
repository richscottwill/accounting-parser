"""Authentik auth adapter — the self-hosted default.

Authentik runs as a sibling container in the Docker Compose stack
(see ``docker-compose.yml`` and ``infra/authentik/``). It exposes:

- OAuth2 / OIDC for token issuance + introspection.
- A management API (``/api/v3/``) for user CRUD and WebAuthn
  credential management.
- A WebAuthn stage that can be chained into login flows.

This adapter handles the two concerns that specifically belong to
the IdP layer:

1. **Token verification.** JWTs signed by Authentik with our
   registered key ring. Verified locally using the JWK endpoint;
   no round-trip per request.
2. **User provisioning at the IdP.** Calls ``/api/v3/core/users/``
   to create records; ``/api/v3/authenticators/webauthn/`` to
   register credentials.

Everything else — the application's ``app_user`` row, tenant
pinning, signup single-firm checks, audit events — lives in
``AuthService``, one layer up.

### What this adapter deliberately does NOT do

- Not a client of ``set_tenant_context`` or the SQLAlchemy session.
  The middleware owns that.
- Not aware of ``passkey_required`` policy — that's AuthService.
- Not a cache. Every JWK lookup is a function of a fresh HTTP call
  plus a 10-minute in-process cache. No Redis, no external cache.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from jose import JWTError, jwt

from accounting_parser.auth.adapter import (
    AuthAdapter,
    AuthenticatedUser,
    AuthProvider,
    PasskeyAssertionError,
    PasskeyCredential,
    SessionToken,
    SessionVerificationError,
    UserRole,
)

_JWK_CACHE_TTL_SECONDS = 600


@dataclass
class AuthentikConfig:
    """Connection + crypto parameters for the Authentik instance.

    In production these come from ``AUTH_ADAPTER_AUTHENTIK_*`` env
    vars resolved through ``pydantic-settings`` in ``config.py``.
    Passed to the adapter as a typed blob so the adapter itself
    doesn't reach into env resolution.
    """

    base_url: str  # e.g., https://authentik.firm.local
    client_id: str  # application ClientID registered in Authentik
    # API token is used for management API calls (user CRUD etc.).
    # NOT used for JWT signing verification.
    api_token: str
    # JWT signing is RS256; public keys fetched from JWKS endpoint.
    jwks_url: str  # usually base_url + /application/o/.../jwks/
    # Tenant + audience must match the Authentik Application configuration.
    audience: str
    issuer: str
    # Our own session signing key — for tokens we mint in-process
    # after Authentik verifies the user's passkey. Authentik verifies
    # the passkey; we mint the app-facing session token so we can bind
    # ``tenant_id`` + ``credential_id_hash`` into claims.
    session_signing_key: str  # PEM-encoded ed25519 private key
    session_signing_kid: str  # key id, matches our JWKS doc


class AuthentikAuthAdapter(AuthAdapter):
    """HTTP client + JWT verifier against a self-hosted Authentik.

    The adapter is stateless except for a small in-process JWK cache.
    All side effects go through the injected ``httpx.AsyncClient``
    so tests can pass a ``MockTransport`` to avoid network calls.
    """

    provider: AuthProvider = AuthProvider.AUTHENTIK

    def __init__(
        self,
        config: AuthentikConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        # The adapter owns the client it creates, but not one passed
        # in (the caller is responsible for closing an injected client).
        self._http = http_client or httpx.AsyncClient(timeout=httpx.Timeout(10.0))
        self._owns_client = http_client is None
        self._jwks_cache: tuple[float, dict[str, Any]] | None = None
        self._cached_public_pem: str | None = None

    async def aclose(self) -> None:
        """Close the owned http client.

        Idempotent. Safe to call on adapters that were given an
        external client (no-op in that case).
        """
        if self._owns_client:
            await self._http.aclose()

    # ---- Public AuthAdapter API ---------------------------------

    async def authenticate_request(self, raw_token: str) -> AuthenticatedUser | None:
        """Verify a session JWT and return the resolved principal.

        We verify our own session token here (minted by
        ``issue_session``), not Authentik's OIDC access token.
        Authentik's token is used once at login to establish the
        passkey; thereafter the application issues short-lived
        RS256/ed25519 session JWTs bound to the credential.

        Returns None for: missing, malformed, expired, bad signature,
        unknown kid, wrong audience, wrong issuer.
        """
        if not raw_token:
            return None
        try:
            # Decode without verification first to read the kid;
            # we need it to pick the public key, then verify.
            unverified = jwt.get_unverified_header(raw_token)
            kid = unverified.get("kid")
            if kid != self.config.session_signing_kid:
                # Unknown kid — caller is presenting a token not
                # issued by this deployment. Silent reject.
                return None

            claims = jwt.decode(
                raw_token,
                self._get_session_public_key_pem(),
                algorithms=["RS256"],
                audience=self.config.audience,
                issuer=self.config.issuer,
            )
        except JWTError:
            return None
        except ValueError:
            # Header parsing failure is not a credential issue —
            # it's a malformed input. Signal structurally.
            raise SessionVerificationError("malformed session token header") from None

        # Required claims: sub (external_id), tid (tenant_id),
        # fid (firm_id, nullable), email, role, exp, credhash (R26.3).
        try:
            expires_at = datetime.fromtimestamp(claims["exp"], tz=UTC)
            user_id = UUID(claims["uid"])
            tenant_id = UUID(claims["tid"])
            firm_id = UUID(claims["fid"]) if claims.get("fid") else None
            role = UserRole(claims["role"])
            # Decode credhash to verify shape; discarded because
            # session binding enforcement lives at step-up routes,
            # not middleware (P2 work). Parsing here still catches
            # malformed tokens before they reach handlers.
            _ = base64.urlsafe_b64decode(claims["credhash"])
        except (KeyError, ValueError, TypeError):
            raise SessionVerificationError("session token missing required claims") from None

        return AuthenticatedUser(
            user_id=user_id,
            tenant_id=tenant_id,
            firm_id=firm_id,
            email=claims["email"],
            role=role,
            external_id=claims["sub"],
            external_provider=AuthProvider.AUTHENTIK,
            session_expires_at=expires_at,
            # True because we only issue session tokens after a
            # passkey assertion verified (``issue_session`` is the
            # only mint site; see below).
            passkey_verified=True,
        )

    async def create_user(
        self,
        *,
        tenant_id: UUID,
        firm_id: UUID,
        email: str,
        role: UserRole,
        display_name: str,
    ) -> str:
        """POST /api/v3/core/users/ to Authentik.

        Returns the provider-assigned user pk (Authentik uses its
        own integer PK but exposes a UUID; we use the ``pk`` string
        because that's what the management API stably returns).
        """
        response = await self._http.post(
            f"{self.config.base_url}/api/v3/core/users/",
            headers=self._mgmt_headers(),
            json={
                "username": email,  # Authentik requires unique username; email is safe
                "email": email,
                "name": display_name,
                "is_active": True,
                "type": "internal",
                # Groups map to Authentik RBAC; role embedded as attribute
                # for audit / filtering, not for AuthN/Z decisions (those
                # live in our schema's ``app_user.role`` CHECK constraint).
                "attributes": {
                    "tenant_id": str(tenant_id),
                    "firm_id": str(firm_id),
                    "app_role": role.value,
                },
            },
        )
        response.raise_for_status()
        body = response.json()
        # Authentik's POST /users/ response includes ``pk``; prefer
        # the uuid field when present for uniformity with other IdPs.
        return str(body.get("uuid") or body["pk"])

    async def enroll_passkey(
        self,
        *,
        external_id: str,
        credential: PasskeyCredential,
    ) -> None:
        """POST /api/v3/authenticators/webauthn/ to Authentik.

        The credential has already been verified at the application
        layer via fido2 (see ``webauthn.py``). Authentik stores it
        so its own login flows can challenge against the same key.
        """
        response = await self._http.post(
            f"{self.config.base_url}/api/v3/authenticators/webauthn/",
            headers=self._mgmt_headers(),
            json={
                "user": external_id,
                "credential_id": base64.urlsafe_b64encode(credential.credential_id).decode(),
                "public_key": base64.urlsafe_b64encode(credential.public_key).decode(),
                "sign_count": credential.sign_count,
                "aaguid": (
                    base64.urlsafe_b64encode(credential.aaguid).decode()
                    if credential.aaguid
                    else None
                ),
                "transports": list(credential.transports),
            },
        )
        response.raise_for_status()

    async def issue_session(
        self,
        *,
        user: AuthenticatedUser,
        credential: PasskeyCredential,
        session_duration_seconds: int,
    ) -> SessionToken:
        """Mint a session JWT bound to the provided credential.

        The token is signed with our session key (RS256 / RSA-2048).
        Claims include ``credhash`` so subsequent requests can be
        rejected if the client somehow presents the token with a
        different credential (R26.3).
        """
        issued_at = datetime.now(UTC)
        expires_at = issued_at + timedelta(seconds=session_duration_seconds)
        credential_id_hash = hashlib.sha256(credential.credential_id).digest()

        claims = {
            "iss": self.config.issuer,
            "aud": self.config.audience,
            "sub": user.external_id,
            "uid": str(user.user_id),
            "tid": str(user.tenant_id),
            "fid": str(user.firm_id) if user.firm_id else None,
            "email": user.email,
            "role": user.role.value,
            "credhash": base64.urlsafe_b64encode(credential_id_hash).decode(),
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
            # jti allows the adapter (and audit log) to reference a
            # specific session by id without exposing the token.
            "jti": secrets.token_urlsafe(16),
        }

        token = jwt.encode(
            claims,
            self.config.session_signing_key,
            algorithm="RS256",
            headers={"kid": self.config.session_signing_kid},
        )

        return SessionToken(
            token=token,
            expires_at=expires_at,
            user_id=user.user_id,
            credential_id_hash=credential_id_hash,
            issued_at=issued_at,
        )

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
        """Thin wrapper over the fido2 helpers.

        The fido2 library handles CTAP2 attestation + assertion
        verification; we only orchestrate inputs and map failures
        into ``PasskeyAssertionError``. Keeping this in the adapter
        means future IdPs that wrap WebAuthn differently (e.g., a
        Passkey-by-proxy service) can implement it their own way.
        """
        # Late import so the module can be loaded in environments
        # that don't have fido2 available (e.g., static analysis of
        # the Protocol). This is the only site that imports fido2.
        from accounting_parser.auth.webauthn import verify_assertion

        try:
            new_sign_count = verify_assertion(
                assertion_cbor=assertion,
                challenge=challenge,
                credential_id=credential_id,
                public_key_cose=public_key,
                stored_sign_count=stored_sign_count,
                expected_origin=self.config.base_url,
                expected_rp_id=_rp_id_from_url(self.config.base_url),
            )
        except Exception as e:  # noqa: BLE001 — we collapse all crypto failures
            # Any verification failure: log internally (middleware
            # will, via audit event), reject externally. Do NOT
            # propagate the specific reason to the client.
            raise PasskeyAssertionError(
                f"passkey assertion for {external_id!r} failed verification"
            ) from e
        return new_sign_count

    async def invalidate_session(self, *, token: str) -> None:
        """Our sessions are stateless JWTs; revocation is best-effort.

        We add the ``jti`` to a Redis-backed revocation set (TTL = the
        token's remaining lifetime). Separate work in P1.2 wires the
        Redis client; for now the hook is a no-op with a clear comment
        so nobody assumes revocation is happening.

        TODO(P1.2): wire revocation-set publication through the Redis
        client added for Celery broker.
        """
        # No-op at P1.1; tests assert the method exists and returns
        # without raising. Real implementation lands in P1.2.
        return

    # ---- Helpers ------------------------------------------------

    def _mgmt_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_token}",
            "Content-Type": "application/json",
        }

    def _get_session_public_key_pem(self) -> str:
        """Return the public half of our session signing key, PEM-encoded.

        Derived once from the configured private key and cached on
        the instance. Verifying with the private key also works but
        python-jose emits a warning our strict-warnings pytest
        config elevates to an error.
        """
        if self._cached_public_pem is not None:
            return self._cached_public_pem
        from cryptography.hazmat.primitives import serialization

        priv = serialization.load_pem_private_key(
            self.config.session_signing_key.encode(), password=None
        )
        pub = priv.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self._cached_public_pem = pub.decode()
        return self._cached_public_pem

    async def _get_jwks(self) -> dict[str, Any]:
        """Fetch and cache Authentik's JWKS.

        Reserved for a future path where Authentik's access tokens
        are verified directly. Currently unused because we mint our
        own session tokens after passkey verification, but kept so
        the adapter can be extended without a second HTTP client.
        """
        now = time.time()
        if self._jwks_cache is not None:
            cached_at, cached_jwks = self._jwks_cache
            if now - cached_at < _JWK_CACHE_TTL_SECONDS:
                return cached_jwks
        response = await self._http.get(self.config.jwks_url)
        response.raise_for_status()
        jwks = response.json()
        self._jwks_cache = (now, jwks)
        return jwks


def _rp_id_from_url(url: str) -> str:
    """Extract the WebAuthn Relying Party ID from a URL.

    RP ID must be the effective domain (no scheme, no port). fido2
    enforces this at assertion verification time, so we derive it
    once here rather than maintaining a separate env var.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return parsed.hostname or ""
