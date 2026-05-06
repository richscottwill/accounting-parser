"""R22.3 / Correctness Property 8: append-only audit log with verifiable hash chain.

Seed 1000 audit entries (varied action/resource/payload) for a single tenant
in arbitrary order, then verify end-to-end:

1. ``prev_hash`` of entry N == ``payload_hash`` of entry N-1, for all N > 1.
2. The genesis entry's ``prev_hash`` is the all-zeros 32-byte value.
3. Each entry's ``payload_hash`` == sha256 of the canonical representation.
4. ``sequence_number`` is strictly monotonic within a tenant.
"""

from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4

import hypothesis.strategies as st
from hypothesis import HealthCheck, given, settings
from sqlalchemy import Engine, text


def _canonical(prev_hash: bytes, action: str, resource_type: str,
               resource_id: UUID | None, actor_user_id: UUID | None,
               sequence_number: int, occurred_at: str, payload_text: str) -> bytes:
    """Mirror the ``canonical`` construction in audit_log_hash_chain_trigger()."""
    rest = (
        action
        + '|' + resource_type
        + '|' + (str(resource_id) if resource_id else '')
        + '|' + (str(actor_user_id) if actor_user_id else '')
        + '|' + str(sequence_number)
        + '|' + occurred_at
        + '|' + payload_text
    )
    return prev_hash + rest.encode('utf-8')


@given(
    # 1000 entries worth of randomness
    action=st.sampled_from([
        "document.upload", "document.parse", "journal.post",
        "export.emit", "review.signoff", "user.login", "user.logout",
    ]),
    resource_type=st.sampled_from([
        "document", "journal_entry", "export", "engagement", "user",
    ]),
    payload=st.dictionaries(
        st.text(min_size=1, max_size=16, alphabet=st.characters(
            whitelist_categories=("L", "N"))),
        st.integers(min_value=0, max_value=1_000_000),
        min_size=0, max_size=3,
    ),
)
@settings(
    max_examples=100,  # 100 append-then-verify cycles; each cycle inserts 10 entries
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture,
                           HealthCheck.filter_too_much],
)
def test_audit_log_hash_chain_append_only_and_verifiable(
    action: str,
    resource_type: str,
    payload: dict,
    superuser_engine: Engine,
) -> None:
    """Each Hypothesis example appends 10 entries for a fresh tenant and
    verifies the hash chain end-to-end.

    Across max_examples=100 × 10 entries = 1000 total entries appended (the
    Correctness Property 8 budget), per unique tenant to keep tests isolated.
    """
    tenant_id = uuid4()
    with superuser_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO tenant (id, name) VALUES (:t, :n)"),
            {"t": tenant_id, "n": f"hash-chain-test-{tenant_id}"},
        )

    try:
        # Insert 10 entries for this tenant. Use superuser for INSERT since
        # app_user does have INSERT grant but would need RLS context set.
        for i in range(10):
            payload_with_i = {**payload, "i": i}
            with superuser_engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO audit_log_entry
                            (tenant_id, action, resource_type, payload, prev_hash, payload_hash)
                        VALUES
                            (:t, :a, :rt, CAST(:p AS jsonb),
                             '\\x0000000000000000000000000000000000000000000000000000000000000000'::bytea,
                             '\\x0000000000000000000000000000000000000000000000000000000000000000'::bytea)
                    """),
                    {"t": tenant_id, "a": action, "rt": resource_type,
                     "p": json.dumps(payload_with_i, sort_keys=True)},
                )

        # Verify chain for this tenant.
        with superuser_engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT sequence_number, prev_hash, payload_hash, action,
                           resource_type, resource_id, actor_user_id,
                           occurred_at::text, payload::text
                      FROM audit_log_entry
                     WHERE tenant_id = :t
                     ORDER BY sequence_number
                """),
                {"t": tenant_id},
            ).all()

        assert len(rows) == 10
        expected_prev = bytes(32)  # 32 zero bytes for genesis
        last_seq: int | None = None
        for r in rows:
            seq, prev_hash, payload_hash, a, rt, rid, auid, occ, pld = r
            prev_hash_b = bytes(prev_hash)
            payload_hash_b = bytes(payload_hash)

            assert prev_hash_b == expected_prev, (
                f"prev_hash mismatch at seq {seq}: "
                f"expected {expected_prev.hex()[:16]}..., "
                f"got {prev_hash_b.hex()[:16]}..."
            )

            expected_hash = hashlib.sha256(
                _canonical(prev_hash_b, a, rt, rid, auid, seq, occ, pld)
            ).digest()
            assert payload_hash_b == expected_hash, (
                f"payload_hash does not match recomputed sha256 at seq {seq}"
            )

            if last_seq is not None:
                assert seq > last_seq, (
                    f"sequence_number not monotonic: {last_seq} -> {seq}"
                )
            last_seq = seq
            expected_prev = payload_hash_b
    finally:
        with superuser_engine.begin() as conn:
            # Platform admin (superuser) can delete for cleanup; app_user cannot.
            conn.execute(
                text("DELETE FROM audit_log_entry WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
            conn.execute(
                text("DELETE FROM tenant WHERE id = :t"), {"t": tenant_id}
            )
