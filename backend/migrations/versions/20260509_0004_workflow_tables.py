"""Workflow engine tables — self-hosted fork reshape (P1.4).

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-09

The parent spec (migration 0001) provisioned placeholder
``workflow_run`` + ``workflow_step_run`` tables with a different
column shape (``workflow_template_id``, ``started_at``, ``ended_at``,
``error_payload``, etc.). The self-hosted fork's WorkflowRunner
tracks additional state (``current_step_index``, ``pause_reason``,
``context``) and uses different column names (``template_id``,
``created_at``, ``updated_at``, ``error``).

This migration drops the parent placeholders and recreates the
tables with the fork's shape. Safe because no workflow data exists
prior to P1.4 — the parent tables were schema-only (Task 17 was
``[~] DEFERRED`` in the parent tasks.md; no code ever wrote to them).

If the parent spec is ever re-instantiated as a separate deployment
path, a compatibility migration would need to live alongside this
one. For the single-firm fork that's out of scope.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DROP_PARENT_TABLES = """
DROP TABLE IF EXISTS workflow_step_run CASCADE;
DROP TABLE IF EXISTS workflow_run CASCADE;
"""


UP_WORKFLOW_RUN = """
CREATE TABLE workflow_run (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    engagement_id uuid NOT NULL REFERENCES engagement(id) ON DELETE RESTRICT,
    template_id text NOT NULL,
    state text NOT NULL CHECK (state IN (
        'pending','running','paused_awaiting_input','completed','failed'
    )),
    current_step_index integer NOT NULL DEFAULT 0,
    pause_reason jsonb NOT NULL DEFAULT '{}'::jsonb,
    context jsonb NOT NULL DEFAULT '{}'::jsonb,
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX workflow_run_tenant_idx ON workflow_run(tenant_id);
CREATE INDEX workflow_run_engagement_idx ON workflow_run(engagement_id);
CREATE INDEX workflow_run_state_idx ON workflow_run(tenant_id, state);

ALTER TABLE workflow_run ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_run FORCE ROW LEVEL SECURITY;
CREATE POLICY workflow_run_tenant_isolation
    ON workflow_run
    FOR ALL
    TO PUBLIC
    USING (tenant_id = app_current_tenant_id())
    WITH CHECK (tenant_id = app_current_tenant_id());

GRANT SELECT, INSERT, UPDATE ON workflow_run TO app_user;

COMMENT ON TABLE workflow_run IS
  'One execution of a named workflow template against an engagement. '
  'State machine: pending -> running -> paused_awaiting_input -> '
  'completed / failed. See workflow/state.py.';
"""

UP_WORKFLOW_STEP_RUN = """
CREATE TABLE workflow_step_run (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    run_id uuid NOT NULL REFERENCES workflow_run(id) ON DELETE CASCADE,
    step_index integer NOT NULL,
    step_name text NOT NULL,
    step_type text NOT NULL,
    state text NOT NULL CHECK (state IN ('running','completed','paused','failed')),
    started_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz,
    attempt integer NOT NULL DEFAULT 1,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    error text
);
CREATE INDEX workflow_step_run_tenant_idx ON workflow_step_run(tenant_id);
CREATE INDEX workflow_step_run_run_idx ON workflow_step_run(run_id, step_index);

ALTER TABLE workflow_step_run ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_step_run FORCE ROW LEVEL SECURITY;
CREATE POLICY workflow_step_run_tenant_isolation
    ON workflow_step_run
    FOR ALL
    TO PUBLIC
    USING (tenant_id = app_current_tenant_id())
    WITH CHECK (tenant_id = app_current_tenant_id());

GRANT SELECT, INSERT, UPDATE ON workflow_step_run TO app_user;

COMMENT ON TABLE workflow_step_run IS
  'One execution attempt of one step within a workflow_run. Append-only '
  'by convention; a second attempt at the same step produces a new row '
  'with attempt = N+1.';
"""


DOWN = """
DROP TABLE IF EXISTS workflow_step_run CASCADE;
DROP TABLE IF EXISTS workflow_run CASCADE;
"""


def upgrade() -> None:
    op.execute(DROP_PARENT_TABLES)
    op.execute(UP_WORKFLOW_RUN)
    op.execute(UP_WORKFLOW_STEP_RUN)


def downgrade() -> None:
    op.execute(DOWN)
