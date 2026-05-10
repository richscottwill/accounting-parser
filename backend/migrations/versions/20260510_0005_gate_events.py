"""OCR field-validation gate_event table (P2.1).

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-10

One row per gated field. Created on OCR extraction, resolved when a
Preparer confirms / corrects / rejects. Unresolved rows block
downstream posting (workflow engine respects ``all_resolved``).

The ``ocr_value`` and ``corrected_value`` are plaintext — these are
the values a Preparer sees on screen while reconciling. They are
*not* raw taxpayer data unless the document itself contained it; the
gate surfaces specific fields, not whole documents. Retention for
resolved events follows the firm's document-retention policy (R27.5).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


UP = """
CREATE TABLE gate_event (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    document_id uuid NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    page_number integer NOT NULL,
    field_label text NOT NULL,
    ocr_value text NOT NULL,
    ocr_confidence numeric(5,4) NOT NULL CHECK (ocr_confidence >= 0 AND ocr_confidence <= 1),
    bounding_box jsonb NOT NULL DEFAULT '{}'::jsonb,
    raw_confidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    resolved_by_user_id uuid REFERENCES app_user(id) ON DELETE SET NULL,
    resolution text CHECK (resolution IN ('confirmed','corrected','rejected')),
    corrected_value text,
    CONSTRAINT gate_event_resolved_consistency CHECK (
        (resolved_at IS NULL AND resolution IS NULL)
        OR (resolved_at IS NOT NULL AND resolution IS NOT NULL)
    )
);
CREATE INDEX gate_event_tenant_idx ON gate_event(tenant_id);
CREATE INDEX gate_event_document_idx ON gate_event(document_id);
CREATE INDEX gate_event_unresolved_idx
    ON gate_event(tenant_id, document_id)
    WHERE resolution IS NULL;

ALTER TABLE gate_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE gate_event FORCE ROW LEVEL SECURITY;
CREATE POLICY gate_event_tenant_isolation
    ON gate_event
    FOR ALL
    TO PUBLIC
    USING (tenant_id = app_current_tenant_id())
    WITH CHECK (tenant_id = app_current_tenant_id());

GRANT SELECT, INSERT, UPDATE ON gate_event TO app_user;

COMMENT ON TABLE gate_event IS
  'OCR field-validation gate events (R29.3). One row per low-confidence '
  'field; resolution sets resolved_at + resolution + corrected_value. '
  'Unresolved rows block downstream posting.';
"""

DOWN = """
DROP TABLE IF EXISTS gate_event;
"""


def upgrade() -> None:
    op.execute(UP)


def downgrade() -> None:
    op.execute(DOWN)
