"""In-memory AuthAdapter for tests.

Deterministic, dependency-free implementation of the ``AuthAdapter``
Protocol. Used by unit tests that exercise the service, middleware,
and route layers without standing up an Authentik container.

The in-memory adapter:

- Stores users in a dict keyed by external_id.
- Records registered passkeys in a dict keyed by external_id.
- Mints session tokens as Ed25519-signed JWTs using a fixed test
  key so the same token verifies in-process.
- Provides a ``verify_passkey_assertion`` that always succeeds when
  the credential is registered (tests inject real fido2 verification
  via ``webauthn.verify_assertion`` separately).

Never used in production. ``create_app`` refuses to construct this
adapter unless the test fixture has injected a pre-built instance.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

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

# Deterministic test key (RSA-2048). Pinned for test reproducibility;
# never ships anywhere. RS256 chosen because python-jose supports it
# natively (its EdDSA/Ed25519 support is not present in the version
# pulled by ``python-jose[cryptography]``). Production installs
# generate their own key via the installer's passphrase-sealed vault.
_TEST_PRIVATE_KEY_PEM = """\
-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQCi63zn8vyMW4SA
uVLtkDnrmZZYWIK6Z0GKI231dUsyelzJOUrsS8kKqdrVja43YrxNucjHu8JT+jiD
9ko1v1M09guGP4DJYZ2b98k2+4c52CnkyAXsounNk2KNcBNHQMRYi4n5CD68JeeJ
PXVKCNv60mbeoF7avAt7E/kxjDZIp1AfXXdfLzMM4DgkMs1rZnE/wA0FSJExvMsb
DQweXsU3KcGrqR/VQz85U5cjtWse9gat7WBYgFZeZxoRRLCQHIIzA6fDuv60HobU
tUQ2Aw5fByCUf6bOuvl6cgQX7WcH+Av0mU+c9PogtDYdxABOdG1dD99LtaUx7U3g
Pkk1pnn1AgMBAAECggEAJnIu4CeprE+edagGJ1SNLolofsGoW+epAjm5JZ7/11Ij
2kKAaUG7GB6cKyALmDtfF3J7rJKk2Z9nPdDdk1BqiMl1T8FlmWBFSryPCcASmbZm
sHv5Ve3eAarBq4HissJYc1K+hPuKnmjNekf8CTQNAWQsbWXn7HNKvEkq2aPuXXdp
0m3FzkFAH17iPFYn859Uiov31AghCNqf/HTIZ+9E6W6Z/cmXMdkCVKvE42h1qaZQ
mFIu1x5YJRJ3WqZvN8W23W8T2QODW5t+jrsB1k3xLh+Eq3+ydVppIlddTWOc22TK
SkNO8S4aeghBXG/uN9W3NAT83eOdCW4Ipcgh1CyAcwKBgQDTK//eIVnssInXAQMQ
WfoKCj+zQgksCyA9KJd9cul53PntVgbFEhG4Lx6gA+3L6cPHLYoqEXFpiM59YC8m
qz87jDdy2bv/LD+fm5IvFsp3w5Dfz6DM2GSVicizCEJ0muBPo21xFnmbRf+aF9HA
dEGhzizwRzwIELiTGUnhOpSDVwKBgQDFgUOwdwOxAE+h4XkUes2kEWptpI8jUec4
JLfFf3UdY7722WtZbDZmPtXeFbfURlqTSDobutoAPF8obhTJpPRXHGyPF9eDX4iX
4Y3fddiuPmwzU+YPmfDhJp/Ff7dbjdDFHTW/evwxAjSQ0mua32wGw6VZp11qwh/h
PbWaNKcJkwKBgQChlE8pxlcqVkKCMxIHFvHNcN4g6WxfOPwoD8Eqihy/1CegRGzV
qefJCLTkN11i47Gb2+qWGdavq7BkGo65hdrSU42x4YyJyW+9TqpiQYwWa5uUxSgC
1ajRCyZ4Zt+CnWb5SNFa8JmIB912KLekDNCTYFDeYYM7oJ+6XmU7Yzlz7QKBgApx
OCv3Tumn044Chs1PZNn81bywS6UZanksb87wWzfPk0Qn4KYcs4+aWOJiEZMWmSla
U0AuE+KZToqrr0ut/gExDohOQWW/wlANa9vZtjgYMs5P7ET85aBx01a01vPvPo99
aN8T2Iuayz6w8WGB2ItPAsoHsEe5tcfJ5HUfvYkjAoGBAMhtdbDaEw8pDdwLxUmi
sAhdsFRkkeL3DhXO0YnYyUEJfWoPR9cKY6OWwDWBvaUjv+XITnr4tzKID9VHXB55
EpJJYr6A7r/iMLvG11wGj2F44E7R8TeQGJ6Ye+Uum7y4i0KWwzGjiLcDC4bgjZ4S
cPESAUMWRiD1uTeqmYyUnsRb
-----END PRIVATE KEY-----
"""

_TEST_KID = "memory-adapter-test-v1"
_TEST_AUDIENCE = "accounting-parser-test"
_TEST_ISSUER = "memory://accounting-parser/test"


@dataclass
class _StoredUser:
    external_id: str
    tenant_id: UUID
    firm_id: UUID | None
    email: str
    role: UserRole
    display_name: str


@dataclass
class MemoryAuthAdapter(AuthAdapter):
    """Test-only adapter. Not exposed to production config paths."""

    provider: AuthProvider = AuthProvider.AUTHENTIK  # behave like authentik
    _users: dict[str, _StoredUser] = field(default_factory=dict)
    _passkeys: dict[str, list[PasskeyCredential]] = field(default_factory=dict)
    _revoked_jtis: set[str] = field(default_factory=set)
    # Counter for synthetic external_ids when no provider-pk is needed.
    _next_id: int = 0

    async def authenticate_request(self, raw_token: str) -> AuthenticatedUser | None:
        if not raw_token:
            return None
        try:
            claims = jwt.decode(
                raw_token,
                _test_public_key_pem(),
                algorithms=["RS256"],
                audience=_TEST_AUDIENCE,
                issuer=_TEST_ISSUER,
            )
        except JWTError:
            return None
        try:
            jti = claims["jti"]
            if jti in self._revoked_jtis:
                return None
            return AuthenticatedUser(
                user_id=UUID(claims["uid"]),
                tenant_id=UUID(claims["tid"]),
                firm_id=UUID(claims["fid"]) if claims.get("fid") else None,
                email=claims["email"],
                role=UserRole(claims["role"]),
                external_id=claims["sub"],
                external_provider=self.provider,
                session_expires_at=datetime.fromtimestamp(claims["exp"], tz=UTC),
                passkey_verified=True,
            )
        except (KeyError, ValueError) as e:
            raise SessionVerificationError("memory adapter: malformed claims") from e

    async def create_user(
        self,
        *,
        tenant_id: UUID,
        firm_id: UUID,
        email: str,
        role: UserRole,
        display_name: str,
    ) -> str:
        self._next_id += 1
        external_id = f"memory-user-{self._next_id}"
        self._users[external_id] = _StoredUser(
            external_id=external_id,
            tenant_id=tenant_id,
            firm_id=firm_id,
            email=email,
            role=role,
            display_name=display_name,
        )
        return external_id

    async def enroll_passkey(
        self,
        *,
        external_id: str,
        credential: PasskeyCredential,
    ) -> None:
        self._passkeys.setdefault(external_id, []).append(credential)

    async def issue_session(
        self,
        *,
        user: AuthenticatedUser,
        credential: PasskeyCredential,
        session_duration_seconds: int,
    ) -> SessionToken:
        issued_at = datetime.now(UTC)
        expires_at = issued_at + timedelta(seconds=session_duration_seconds)
        cred_hash = hashlib.sha256(credential.credential_id).digest()
        claims: dict[str, Any] = {
            "iss": _TEST_ISSUER,
            "aud": _TEST_AUDIENCE,
            "sub": user.external_id,
            "uid": str(user.user_id),
            "tid": str(user.tenant_id),
            "fid": str(user.firm_id) if user.firm_id else None,
            "email": user.email,
            "role": user.role.value,
            "credhash": base64.urlsafe_b64encode(cred_hash).decode(),
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
            "jti": secrets.token_urlsafe(16),
        }
        token = jwt.encode(
            claims,
            _TEST_PRIVATE_KEY_PEM,
            algorithm="RS256",
            headers={"kid": _TEST_KID},
        )
        return SessionToken(
            token=token,
            expires_at=expires_at,
            user_id=user.user_id,
            credential_id_hash=cred_hash,
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
        # Test-only: accept any assertion for a registered credential
        # and increment sign_count. Cryptographic path is exercised
        # by tests that use the real AuthentikAuthAdapter.
        stored = self._passkeys.get(external_id, [])
        if not any(c.credential_id == credential_id for c in stored):
            raise PasskeyAssertionError("unregistered credential")
        return stored_sign_count + 1

    async def invalidate_session(self, *, token: str) -> None:
        try:
            claims = jwt.decode(
                token,
                _test_public_key_pem(),
                algorithms=["RS256"],
                audience=_TEST_AUDIENCE,
                issuer=_TEST_ISSUER,
            )
            self._revoked_jtis.add(claims["jti"])
        except JWTError:
            # Best-effort; match Authentik's behavior.
            pass


def _test_public_key_pem() -> str:
    """Derive the public half of the test RSA key.

    Cached at module level so repeated verifications don't re-parse
    the private key every time. Verifying with the private key also
    works but python-jose emits a warning our pyproject elevates to
    an error.
    """
    global _CACHED_PUBLIC_PEM
    if _CACHED_PUBLIC_PEM is not None:
        return _CACHED_PUBLIC_PEM
    from cryptography.hazmat.primitives import serialization

    priv = serialization.load_pem_private_key(_TEST_PRIVATE_KEY_PEM.encode(), password=None)
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    _CACHED_PUBLIC_PEM = pub_pem.decode()
    return _CACHED_PUBLIC_PEM


_CACHED_PUBLIC_PEM: str | None = None


def signing_key_pem_for_tests() -> str:
    """Return the test signing key, for fixtures that wire settings."""
    return _TEST_PRIVATE_KEY_PEM


def kid_for_tests() -> str:
    return _TEST_KID


def audience_for_tests() -> str:
    return _TEST_AUDIENCE


def issuer_for_tests() -> str:
    return _TEST_ISSUER
