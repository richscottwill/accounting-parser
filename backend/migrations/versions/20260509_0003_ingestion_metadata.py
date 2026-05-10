"""Ingestion metadata columns for the self-hosted fork.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-09

Extends ``document`` with columns the P1.2 ingestion pipeline
populates:

- ``declared_content_type``    — what the client said the file was.
  Kept alongside ``content_type`` (which holds the detected value)
  so audits can reconstruct a lying-client pattern over time.
- ``scan_state``               — 'pending', 'clean', 'infected',
  'scanner_unavailable'.
- ``scan_signature``           — nullable; populated when infected.
- ``quarantine_key``           — nullable; populated for rejected
  uploads whose bytes we stashed in quarantine prefix.
- ``encryption_key_id``        — nullable; P1.3 populates this
  with the KMS adapter's key-ref handle. Left nullable here so
  rows inserted before P1.3 don't break.

No new tables. The ``quarantine`` / ``rejected`` paths don't get
rows in ``document`` — they get audit_log_entry rows only. This
keeps dedup + parsing logic downstream from having to filter on
state.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


UP = """
ALTER TABLE document
    ADD COLUMN declared_content_type text,
    ADD COLUMN scan_state text NOT NULL DEFAULT 'pending'
        CHECK (scan_state IN ('pending', 'clean', 'infected', 'scanner_unavailable')),
    ADD COLUMN scan_signature text,
    ADD COLUMN scan_scanner_version text,
    ADD COLUMN quarantine_key text,
    ADD COLUMN encryption_key_id text;

COMMENT ON COLUMN document.declared_content_type IS
  'Client-declared content-type at upload time. Retained to audit '
  'declared-vs-detected mismatch patterns.';
COMMENT ON COLUMN document.scan_state IS
  'Virus-scan state: pending | clean | infected | scanner_unavailable. '
  'Infected and scanner_unavailable paths never insert a document row — '
  'this column is populated for reporting on the clean path.';
COMMENT ON COLUMN document.encryption_key_id IS
  'Handle returned by the KMS adapter for this object''s per-Client DEK. '
  'Populated by P1.3 (SoftwareVaultAdapter). Nullable for compat with '
  'P1.2-era rows.';

-- On the clean path the ingestion service writes scan_state='clean'
-- directly from the scanner result. Pending default covers any path
-- that inserts via a future migration or backfill without scanning.

-- Elevate the hash-chain trigger to SECURITY DEFINER so it can
-- acquire FOR UPDATE row locks on audit_log_entry when invoked by
-- app_user (which lacks UPDATE permission on the table by design).
-- The function body is unchanged; only its execution context is
-- promoted. Ownership stays with the migration role (postgres /
-- platform_admin in test fixtures), so FOR UPDATE succeeds while
-- the REVOKE UPDATE/DELETE on the TABLE still prevents the caller
-- from modifying existing rows.
CREATE OR REPLACE FUNCTION audit_log_hash_chain_trigger()
RETURNS trigger LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    last_hash bytea;
    canonical bytea;
BEGIN
    SELECT payload_hash INTO last_hash
      FROM audit_log_entry
     WHERE tenant_id = NEW.tenant_id
     ORDER BY sequence_number DESC
     LIMIT 1
     FOR UPDATE;

    IF last_hash IS NULL THEN
        last_hash := repeat('\\000', 32)::bytea;
    END IF;

    NEW.prev_hash := last_hash;

    canonical :=
        NEW.prev_hash ||
        convert_to(
            NEW.action
            || '|' || NEW.resource_type
            || '|' || coalesce(NEW.resource_id::text, '')
            || '|' || coalesce(NEW.actor_user_id::text, '')
            || '|' || NEW.sequence_number::text
            || '|' || NEW.occurred_at::text
            || '|' || NEW.payload::text,
            'UTF8'
        );

    NEW.payload_hash := sha256(canonical);
    RETURN NEW;
END;
$$;
"""


DOWN = """
ALTER TABLE document
    DROP COLUMN encryption_key_id,
    DROP COLUMN quarantine_key,
    DROP COLUMN scan_scanner_version,
    DROP COLUMN scan_signature,
    DROP COLUMN scan_state,
    DROP COLUMN declared_content_type;
"""


def upgrade() -> None:
    op.execute(UP)


def downgrade() -> None:
    op.execute(DOWN)
