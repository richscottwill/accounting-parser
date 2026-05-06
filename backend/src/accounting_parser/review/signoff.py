"""ReviewSignoff records: cryptographically bound to reviewer + payload."""

from __future__ import annotations

import hmac
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict


class SignoffLevel(str, Enum):
    PREPARER = "preparer"
    FIRST_REVIEWER = "first_reviewer"
    SECOND_REVIEWER = "second_reviewer"
    PARTNER = "partner"


def _canonical_payload_bytes(payload: dict[str, Any]) -> bytes:
    """Stable canonical byte representation of a payload dict."""
    import json
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str).encode("utf-8")


class ReviewSignoff(BaseModel):
    """An append-only reviewer signoff record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signoff_id: UUID
    tenant_id: UUID
    engagement_id: UUID
    artifact_type: str
    artifact_id: UUID
    signoff_level: SignoffLevel
    signed_off_by_user_id: UUID
    signed_off_at: datetime
    notes: str | None = None
    hmac_hex: str
    reverses_signoff_id: UUID | None = None


def _compute_hmac(
    *,
    tenant_key: bytes,
    tenant_id: UUID,
    engagement_id: UUID,
    artifact_type: str,
    artifact_id: UUID,
    signoff_level: SignoffLevel,
    signed_off_by_user_id: UUID,
    signed_off_at: datetime,
    payload: dict[str, Any],
    reverses_signoff_id: UUID | None,
) -> str:
    canonical = (
        str(tenant_id).encode()
        + b"|" + str(engagement_id).encode()
        + b"|" + artifact_type.encode()
        + b"|" + str(artifact_id).encode()
        + b"|" + signoff_level.value.encode()
        + b"|" + str(signed_off_by_user_id).encode()
        + b"|" + signed_off_at.isoformat().encode()
        + b"|" + _canonical_payload_bytes(payload)
        + b"|" + (str(reverses_signoff_id).encode() if reverses_signoff_id else b"")
    )
    return hmac.new(tenant_key, canonical, sha256).hexdigest()


def create_signoff(
    *,
    tenant_key: bytes,
    tenant_id: UUID,
    engagement_id: UUID,
    artifact_type: str,
    artifact_id: UUID,
    signoff_level: SignoffLevel,
    signed_off_by_user_id: UUID,
    payload: dict[str, Any],
    notes: str | None = None,
) -> ReviewSignoff:
    """Create a new signoff bound to the artifact + reviewer."""
    now = datetime.now(timezone.utc)
    mac = _compute_hmac(
        tenant_key=tenant_key,
        tenant_id=tenant_id,
        engagement_id=engagement_id,
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        signoff_level=signoff_level,
        signed_off_by_user_id=signed_off_by_user_id,
        signed_off_at=now,
        payload=payload,
        reverses_signoff_id=None,
    )
    return ReviewSignoff(
        signoff_id=uuid4(),
        tenant_id=tenant_id,
        engagement_id=engagement_id,
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        signoff_level=signoff_level,
        signed_off_by_user_id=signed_off_by_user_id,
        signed_off_at=now,
        notes=notes,
        hmac_hex=mac,
    )


def reverse_signoff(
    original: ReviewSignoff,
    *,
    tenant_key: bytes,
    reviewer_id: UUID,
    notes: str | None = None,
    payload: dict[str, Any] | None = None,
) -> ReviewSignoff:
    """Reverse a prior signoff by creating a new append-only record that
    references the original via ``reverses_signoff_id``. The original is
    never edited."""
    now = datetime.now(timezone.utc)
    payload = payload or {}
    mac = _compute_hmac(
        tenant_key=tenant_key,
        tenant_id=original.tenant_id,
        engagement_id=original.engagement_id,
        artifact_type=original.artifact_type,
        artifact_id=original.artifact_id,
        signoff_level=original.signoff_level,
        signed_off_by_user_id=reviewer_id,
        signed_off_at=now,
        payload=payload,
        reverses_signoff_id=original.signoff_id,
    )
    return ReviewSignoff(
        signoff_id=uuid4(),
        tenant_id=original.tenant_id,
        engagement_id=original.engagement_id,
        artifact_type=original.artifact_type,
        artifact_id=original.artifact_id,
        signoff_level=original.signoff_level,
        signed_off_by_user_id=reviewer_id,
        signed_off_at=now,
        notes=notes,
        hmac_hex=mac,
        reverses_signoff_id=original.signoff_id,
    )


def verify_signoff(
    signoff: ReviewSignoff,
    *,
    tenant_key: bytes,
    payload: dict[str, Any],
) -> bool:
    """Return True iff the stored HMAC matches a recomputation."""
    expected = _compute_hmac(
        tenant_key=tenant_key,
        tenant_id=signoff.tenant_id,
        engagement_id=signoff.engagement_id,
        artifact_type=signoff.artifact_type,
        artifact_id=signoff.artifact_id,
        signoff_level=signoff.signoff_level,
        signed_off_by_user_id=signoff.signed_off_by_user_id,
        signed_off_at=signoff.signed_off_at,
        payload=payload,
        reverses_signoff_id=signoff.reverses_signoff_id,
    )
    return hmac.compare_digest(expected, signoff.hmac_hex)
