"""Task 6 ingestion: extend the Task 3 document table with fields the
Ingestion Service needs.

Task 3's ``document`` already holds filename, content_type, byte_size,
sha256, s3_bucket/s3_key, source_system, source_confidence, ingest_state,
uploaded_by_user_id, uploaded_at, and the (tenant_id, client_id, sha256)
dedup unique constraint. Task 6 adds:

- ``declared_mime``: what the uploader claimed (Task 3 conflated declared
  and detected into ``content_type``).
- ``scan_state`` / ``scan_engine`` / ``scan_finding``: malware scan result.
- ``pbc_request_id``: optional link to the PBC item this upload satisfies.
- ``rejection_reason``: free-text for support.
- Index ``document_ingest_state_idx`` to power queue views.

Task 3's ingest_state enum doesn't include ``received``, ``scanning``, or
``queued`` — Task 6's state machine introduces them via a widened CHECK
constraint.

Revision ID: 0003
Revises: 0002
"""
from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


UP_SQL = """
-- Widen ingest_state to cover Task 6's flow states.
ALTER TABLE document DROP CONSTRAINT IF EXISTS document_ingest_state_check;
ALTER TABLE document ADD CONSTRAINT document_ingest_state_check
    CHECK (ingest_state IN (
        'uploaded','received','scanning','queued','scanned',
        'detected','parsing','parsed','failed','quarantined','rejected'
    ));

ALTER TABLE document
    ADD COLUMN IF NOT EXISTS declared_mime text,
    ADD COLUMN IF NOT EXISTS scan_state text NOT NULL DEFAULT 'pending'
        CHECK (scan_state IN ('pending','clean','infected','skipped','error')),
    ADD COLUMN IF NOT EXISTS scan_engine text,
    ADD COLUMN IF NOT EXISTS scan_finding text,
    ADD COLUMN IF NOT EXISTS pbc_request_id uuid
        REFERENCES pbc_request(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS rejection_reason text;

CREATE INDEX IF NOT EXISTS document_ingest_state_idx ON document(ingest_state);
CREATE INDEX IF NOT EXISTS document_pbc_idx ON document(pbc_request_id);

-- The Task 3 audit_log_hash_chain_trigger uses ``SELECT ... FOR UPDATE``
-- to serialize chain-append, which requires row-level UPDATE privilege.
-- app_user is intentionally NOBYPASSRLS with UPDATE + DELETE revoked on
-- audit_log_entry (append-only). Promote the trigger function to
-- SECURITY DEFINER so the serialization lock runs with the owner's
-- (platform_admin) privileges — the INSERT itself still runs under the
-- invoker's identity and its row still carries the invoker's actor_user_id.
ALTER FUNCTION audit_log_hash_chain_trigger() SECURITY DEFINER;
"""


DOWN_SQL = """
ALTER TABLE document
    DROP COLUMN IF EXISTS rejection_reason,
    DROP COLUMN IF EXISTS pbc_request_id,
    DROP COLUMN IF EXISTS scan_finding,
    DROP COLUMN IF EXISTS scan_engine,
    DROP COLUMN IF EXISTS scan_state,
    DROP COLUMN IF EXISTS declared_mime;

ALTER TABLE document DROP CONSTRAINT IF EXISTS document_ingest_state_check;
ALTER TABLE document ADD CONSTRAINT document_ingest_state_check
    CHECK (ingest_state IN (
        'uploaded','scanned','detected','parsed','failed','quarantined'
    ));
"""


def upgrade() -> None:
    op.execute(UP_SQL)


def downgrade() -> None:
    op.execute(DOWN_SQL)
