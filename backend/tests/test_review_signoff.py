"""ReviewSignoff HMAC integrity tests."""

from __future__ import annotations

import os
from uuid import uuid4

from accounting_parser.review import (
    SignoffLevel,
    create_signoff,
    reverse_signoff,
    verify_signoff,
)


def _tenant_key() -> bytes:
    return os.urandom(32)


def test_signoff_verifies() -> None:
    key = _tenant_key()
    tenant = uuid4()
    eng = uuid4()
    art = uuid4()
    reviewer = uuid4()
    payload = {"financial_total": "123456.78", "rows": 42}
    so = create_signoff(
        tenant_key=key, tenant_id=tenant, engagement_id=eng,
        artifact_type="lead_schedule", artifact_id=art,
        signoff_level=SignoffLevel.FIRST_REVIEWER,
        signed_off_by_user_id=reviewer, payload=payload,
    )
    assert verify_signoff(so, tenant_key=key, payload=payload)


def test_tampered_payload_fails_verification() -> None:
    key = _tenant_key()
    so = create_signoff(
        tenant_key=key, tenant_id=uuid4(), engagement_id=uuid4(),
        artifact_type="x", artifact_id=uuid4(),
        signoff_level=SignoffLevel.PREPARER,
        signed_off_by_user_id=uuid4(),
        payload={"total": "100"},
    )
    # Same signoff, different payload
    assert not verify_signoff(so, tenant_key=key, payload={"total": "999"})


def test_wrong_key_fails_verification() -> None:
    key_a = _tenant_key()
    key_b = _tenant_key()
    so = create_signoff(
        tenant_key=key_a, tenant_id=uuid4(), engagement_id=uuid4(),
        artifact_type="x", artifact_id=uuid4(),
        signoff_level=SignoffLevel.PARTNER,
        signed_off_by_user_id=uuid4(),
        payload={},
    )
    assert not verify_signoff(so, tenant_key=key_b, payload={})


def test_reversal_is_new_record_not_edit() -> None:
    key = _tenant_key()
    original = create_signoff(
        tenant_key=key, tenant_id=uuid4(), engagement_id=uuid4(),
        artifact_type="binder", artifact_id=uuid4(),
        signoff_level=SignoffLevel.SECOND_REVIEWER,
        signed_off_by_user_id=uuid4(),
        payload={"status": "signed"},
    )
    reversal = reverse_signoff(original, tenant_key=key, reviewer_id=uuid4(),
                               notes="found error")
    # Reversal has a NEW signoff_id, references the original
    assert reversal.signoff_id != original.signoff_id
    assert reversal.reverses_signoff_id == original.signoff_id
    # Reversal has its own HMAC, not the original's
    assert reversal.hmac_hex != original.hmac_hex
    # Reversal verifies against its own payload
    assert verify_signoff(reversal, tenant_key=key, payload={})
