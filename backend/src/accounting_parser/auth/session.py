"""App-layer session JWT issuance and validation.

After a successful WebAuthn assertion, the app mints a short-lived JWT
signed with ``settings.session_secret`` (HS256). The JWT carries:
- ``sub``: the app_user.id (UUID)
- ``tenant_id``: the user's tenant
- ``firm_id``: the user's firm
- ``role``: firm_administrator / preparer / reviewer / client_portal
- ``email``
- ``iat``, ``exp``

This is the token middleware consumes to set RLS context on every request.
It is distinct from Cognito's own token — Cognito is used for identity
allocation (sub UUID) at signup; the app-issued JWT is what clients
present on subsequent API calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from jose import JWTError, jwt

from accounting_parser.config import Settings, get_settings


@dataclass(frozen=True)
class SessionClaims:
    """Decoded session JWT payload."""

    user_id: UUID
    tenant_id: UUID
    firm_id: UUID | None
    role: str
    email: str
    iat: datetime
    exp: datetime


def issue_session_token(
    *,
    user_id: UUID,
    tenant_id: UUID,
    firm_id: UUID | None,
    role: str,
    email: str,
    settings: Settings | None = None,
) -> str:
    """Mint a session JWT."""
    settings = settings or get_settings()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "firm_id": str(firm_id) if firm_id else None,
        "role": role,
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.session_ttl_hours)).timestamp()),
    }
    return jwt.encode(payload, settings.session_secret, algorithm="HS256")


def decode_session_token(
    token: str, *, settings: Settings | None = None
) -> SessionClaims:
    """Validate + decode a session JWT. Raises ValueError on any failure."""
    settings = settings or get_settings()
    try:
        payload = jwt.decode(token, settings.session_secret, algorithms=["HS256"])
    except JWTError as e:
        raise ValueError(f"Invalid session token: {e}") from e

    try:
        return SessionClaims(
            user_id=UUID(payload["sub"]),
            tenant_id=UUID(payload["tenant_id"]),
            firm_id=UUID(payload["firm_id"]) if payload.get("firm_id") else None,
            role=payload["role"],
            email=payload["email"],
            iat=datetime.fromtimestamp(payload["iat"], tz=timezone.utc),
            exp=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        )
    except (KeyError, ValueError, TypeError) as e:
        raise ValueError(f"Malformed session token payload: {e}") from e
