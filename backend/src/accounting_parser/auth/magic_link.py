"""Magic-link authentication for the Client portal.

Requirement source: R26.4 (Client portal auth) — magic-link with
15-minute TTL, followed by mandatory passkey enrollment on first
login.

### Design choices

- **Token format:** URL-safe random 32 bytes → 43 chars. Not a JWT;
  we don't want the token to self-describe. Revocation and TTL are
  enforced by the database.
- **Storage:** Row in ``magic_link_token`` table (added in migration
  0002). Columns: id, tenant_id, email, token_hash (sha256), issued_at,
  expires_at, used_at, used_from_ip. The hash — not the raw token —
  is stored. A leaked DB dump does not grant attacker access; a
  malicious DBA still can't forge tokens without the hash preimage.
- **Single-use:** ``used_at`` is set atomically on consumption. Any
  subsequent verify call sees the row as used and rejects.
- **Audit:** every issue + verify + reject logged into
  ``audit_log_entry`` (action=``auth.magic_link.*``).

### What this module does NOT do

- Does not send emails. That's the Client Portal route which calls
  ``MagicLinkService.issue()`` then hands the resulting raw token
  to the email adapter (defined in P2 compliance stack).
- Does not enforce passkey enrollment on first use. That's
  ``AuthService.handle_magic_link_consumed()``, which upgrades the
  session to "must_enroll_passkey" state until enrollment succeeds.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

MAGIC_LINK_DEFAULT_TTL_SECONDS = 15 * 60  # R26.4


@dataclass(frozen=True)
class IssuedMagicLink:
    """Result of ``MagicLinkService.issue()``.

    ``raw_token`` MUST be delivered to the user via email and then
    discarded — we never persist it. ``expires_at`` is returned for
    the email template to render.
    """

    raw_token: str
    token_hash: bytes
    expires_at: datetime
    email: str
    tenant_id: UUID


@dataclass(frozen=True)
class ConsumedMagicLink:
    """Result of ``MagicLinkService.consume()`` on a valid token.

    The caller uses ``email`` + ``tenant_id`` to resolve the
    corresponding ``app_user`` and issue an upgrade-path session
    (must_enroll_passkey=True until enrollment completes).
    """

    email: str
    tenant_id: UUID


class InvalidMagicLinkError(RuntimeError):
    """Raised when a magic-link token fails any validation check.

    Single error type across: unknown token, expired, already used,
    wrong tenant scope. Single type prevents oracle-style enumeration.
    """


def generate_token() -> tuple[str, bytes]:
    """Produce a fresh magic-link token and its sha256 digest.

    The raw token is returned so the caller (route handler) can email
    it; the hash is what gets persisted. Callers MUST NOT persist
    the raw token.
    """
    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode("ascii")).digest()
    return raw, digest


def compute_token_hash(raw_token: str) -> bytes:
    """Derive the stored digest from a presented raw token."""
    return hashlib.sha256(raw_token.encode("ascii")).digest()


def default_expiry(
    issued_at: datetime | None = None,
    ttl_seconds: int = MAGIC_LINK_DEFAULT_TTL_SECONDS,
) -> datetime:
    """Compute the expiry timestamp for a fresh magic-link token."""
    at = issued_at or datetime.now(UTC)
    return at + timedelta(seconds=ttl_seconds)
