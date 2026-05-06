"""Initial schema: tenancy, core domain, RLS, audit hash chain

Revision ID: 0001
Revises:
Create Date: 2026-05-05

Creates the complete Task 3 schema in a single migration:
- Roles: ``app_user`` (NOBYPASSRLS), ``platform_admin`` (BYPASSRLS)
- 20 core tables per design §2
- Row-Level Security policies using ``current_setting('app.tenant_id')``
- Immutable audit_log_entry with SHA-256 hash-chain trigger
- REVOKE UPDATE/DELETE on audit_log_entry from app_user

Design references:
- requirements.md R1.10, R22.1, R22.2, R22.3
- design.md §4.2 (RLS), §4.3 (audit hash chain)

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# --- Roles and helper function ------------------------------------------------

ROLES_UP = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        CREATE ROLE app_user NOLOGIN NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'platform_admin') THEN
        CREATE ROLE platform_admin NOLOGIN BYPASSRLS;
    END IF;
END
$$;
"""

# Helper function: resolve the current tenant from session setting. RLS
# policies call this so the setting key is defined in one place.
HELPER_UP = """
CREATE OR REPLACE FUNCTION app_current_tenant_id() RETURNS uuid
LANGUAGE sql STABLE AS $$
    SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid;
$$;
COMMENT ON FUNCTION app_current_tenant_id() IS
  'Returns the current session tenant_id from the app.tenant_id setting. '
  'NULL if not set. RLS policies use this.';
"""


# --- Core tables --------------------------------------------------------------

# A note on ordering:
# - ``tenant`` and ``firm`` are top-level; all others reference them.
# - ``tenant_id`` column is denormalized onto every tenant-scoped table so RLS
#   can filter on a single column without JOIN. Per design §4.2.

TABLES_UP = """
-- Tenant: the billing + isolation boundary. One per customer firm.
CREATE TABLE tenant (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    kms_key_alias text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT tenant_name_unique UNIQUE (name)
);

-- Firm: an accounting firm operating within a tenant. Usually 1:1 with
-- tenant at MVP; multi-firm tenants are a post-MVP feature.
CREATE TABLE firm (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    name text NOT NULL,
    ptin text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX firm_tenant_idx ON firm(tenant_id);

-- User: preparers and client-portal users. Cognito is the identity
-- provider; this row mirrors the Cognito sub for local joins.
CREATE TABLE app_user (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    firm_id uuid REFERENCES firm(id) ON DELETE SET NULL,
    cognito_sub text NOT NULL,
    email text NOT NULL,
    role text NOT NULL CHECK (role IN (
        'firm_administrator','preparer','reviewer','client_portal')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT app_user_cognito_sub_unique UNIQUE (cognito_sub),
    CONSTRAINT app_user_tenant_email_unique UNIQUE (tenant_id, email)
);
CREATE INDEX app_user_tenant_idx ON app_user(tenant_id);
CREATE INDEX app_user_firm_idx ON app_user(firm_id);

-- Client: the firm's customer.
CREATE TABLE client (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    firm_id uuid NOT NULL REFERENCES firm(id) ON DELETE RESTRICT,
    name text NOT NULL,
    ein text,
    entity_type text CHECK (entity_type IN (
        'c_corporation','s_corporation','partnership','sole_proprietorship',
        'llc','other')),
    fiscal_year_end_month smallint CHECK (fiscal_year_end_month BETWEEN 1 AND 12),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX client_tenant_idx ON client(tenant_id);
CREATE INDEX client_firm_idx ON client(firm_id);

-- Engagement: a discrete piece of work for a client (e.g., 2024 tax return).
CREATE TABLE engagement (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    client_id uuid NOT NULL REFERENCES client(id) ON DELETE RESTRICT,
    name text NOT NULL,
    engagement_type text NOT NULL CHECK (engagement_type IN (
        'tax_return','financial_statement','compilation','review',
        'bookkeeping','other')),
    tax_year smallint,
    period_start date,
    period_end date,
    status text NOT NULL DEFAULT 'in_progress' CHECK (status IN (
        'planning','in_progress','review','signed_off','delivered','archived')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX engagement_tenant_idx ON engagement(tenant_id);
CREATE INDEX engagement_client_idx ON engagement(client_id);

-- Document: every uploaded source doc.
CREATE TABLE document (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    engagement_id uuid NOT NULL REFERENCES engagement(id) ON DELETE RESTRICT,
    client_id uuid NOT NULL REFERENCES client(id) ON DELETE RESTRICT,
    filename text NOT NULL,
    content_type text NOT NULL,
    byte_size bigint NOT NULL,
    sha256 bytea NOT NULL,
    s3_bucket text NOT NULL,
    s3_key text NOT NULL,
    source_system text,
    source_confidence numeric(4,3),
    ingest_state text NOT NULL DEFAULT 'uploaded' CHECK (ingest_state IN (
        'uploaded','scanned','detected','parsed','failed','quarantined')),
    uploaded_by_user_id uuid REFERENCES app_user(id) ON DELETE SET NULL,
    uploaded_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT document_dedup_unique UNIQUE (tenant_id, client_id, sha256)
);
CREATE INDEX document_tenant_idx ON document(tenant_id);
CREATE INDEX document_engagement_idx ON document(engagement_id);
CREATE INDEX document_client_idx ON document(client_id);

-- ParseResult: output of a parser run against a Document.
CREATE TABLE parse_result (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    document_id uuid NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    schema_version integer NOT NULL DEFAULT 1,
    report_type text NOT NULL,
    payload jsonb NOT NULL,
    parse_status text NOT NULL CHECK (parse_status IN ('ok','partial','failed')),
    parsed_at timestamptz NOT NULL DEFAULT now(),
    parser_version text NOT NULL
);
CREATE INDEX parse_result_tenant_idx ON parse_result(tenant_id);
CREATE INDEX parse_result_doc_idx ON parse_result(document_id);

-- Account: normalized chart of accounts entry. Identity is
-- (tenant_id, client_id, account_number) per design §3.6.
CREATE TABLE account (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    client_id uuid NOT NULL REFERENCES client(id) ON DELETE RESTRICT,
    account_number text NOT NULL,
    account_name text NOT NULL,
    account_type text,
    category text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT account_client_number_unique UNIQUE (tenant_id, client_id, account_number)
);
CREATE INDEX account_tenant_idx ON account(tenant_id);
CREATE INDEX account_client_idx ON account(client_id);

-- Working Trial Balance rows.
CREATE TABLE working_trial_balance_row (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    engagement_id uuid NOT NULL REFERENCES engagement(id) ON DELETE CASCADE,
    account_id uuid NOT NULL REFERENCES account(id) ON DELETE RESTRICT,
    prior_year numeric(18,2) NOT NULL DEFAULT 0,
    unadjusted numeric(18,2) NOT NULL DEFAULT 0,
    sum_aje numeric(18,2) NOT NULL DEFAULT 0,
    adjusted numeric(18,2) NOT NULL DEFAULT 0,
    sum_rje numeric(18,2) NOT NULL DEFAULT 0,
    final numeric(18,2) NOT NULL DEFAULT 0,
    sum_tje numeric(18,2) NOT NULL DEFAULT 0,
    tax_basis numeric(18,2) NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT wtb_row_unique UNIQUE (engagement_id, account_id)
);
CREATE INDEX wtb_tenant_idx ON working_trial_balance_row(tenant_id);

-- Journal Entry Adjustment (AJE/RJE/TJE).
CREATE TABLE journal_entry_adjustment (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    engagement_id uuid NOT NULL REFERENCES engagement(id) ON DELETE CASCADE,
    entry_type text NOT NULL CHECK (entry_type IN ('aje','rje','tje','elim')),
    description text NOT NULL,
    posted_at timestamptz,
    posted_by_user_id uuid REFERENCES app_user(id) ON DELETE SET NULL,
    status text NOT NULL DEFAULT 'proposed' CHECK (status IN (
        'proposed','approved','posted','rejected','reversed')),
    template_id text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX jea_tenant_idx ON journal_entry_adjustment(tenant_id);
CREATE INDEX jea_engagement_idx ON journal_entry_adjustment(engagement_id);

-- Journal Leg: individual debit/credit lines.
CREATE TABLE journal_leg (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    journal_entry_id uuid NOT NULL REFERENCES journal_entry_adjustment(id) ON DELETE CASCADE,
    account_id uuid NOT NULL REFERENCES account(id) ON DELETE RESTRICT,
    debit numeric(18,2) NOT NULL DEFAULT 0,
    credit numeric(18,2) NOT NULL DEFAULT 0,
    memo text,
    CONSTRAINT journal_leg_dr_or_cr CHECK (
        (debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)
    )
);
CREATE INDEX journal_leg_tenant_idx ON journal_leg(tenant_id);
CREATE INDEX journal_leg_entry_idx ON journal_leg(journal_entry_id);

-- Fixed Asset.
CREATE TABLE fixed_asset (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    client_id uuid NOT NULL REFERENCES client(id) ON DELETE RESTRICT,
    asset_id text NOT NULL,
    description text NOT NULL,
    class_life smallint NOT NULL,
    placed_in_service date NOT NULL,
    cost_basis numeric(18,2) NOT NULL,
    section_179 numeric(18,2) NOT NULL DEFAULT 0,
    bonus_rate numeric(5,4) NOT NULL DEFAULT 0,
    disposed_at date,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fixed_asset_client_asset_unique UNIQUE (tenant_id, client_id, asset_id)
);
CREATE INDEX fixed_asset_tenant_idx ON fixed_asset(tenant_id);

-- Tax Line Mapping: account -> tax-form line.
CREATE TABLE tax_line_mapping (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    client_id uuid NOT NULL REFERENCES client(id) ON DELETE RESTRICT,
    account_id uuid NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    form text NOT NULL,
    line_id text NOT NULL,
    tax_year smallint NOT NULL,
    confidence numeric(4,3),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX tax_line_mapping_tenant_idx ON tax_line_mapping(tenant_id);
CREATE INDEX tax_line_mapping_account_idx ON tax_line_mapping(account_id);

-- PBC (Prepared By Client) Request.
CREATE TABLE pbc_request (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    engagement_id uuid NOT NULL REFERENCES engagement(id) ON DELETE CASCADE,
    title text NOT NULL,
    description text,
    status text NOT NULL DEFAULT 'open' CHECK (status IN (
        'open','sent','in_progress','received','closed','waived')),
    due_at date,
    assigned_to_user_id uuid REFERENCES app_user(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX pbc_tenant_idx ON pbc_request(tenant_id);

-- Workflow Run: an executing workflow instance.
CREATE TABLE workflow_run (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    engagement_id uuid NOT NULL REFERENCES engagement(id) ON DELETE CASCADE,
    workflow_template_id text NOT NULL,
    state text NOT NULL CHECK (state IN (
        'pending','running','paused_awaiting_input','completed','failed')),
    started_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz,
    error_payload jsonb
);
CREATE INDEX workflow_run_tenant_idx ON workflow_run(tenant_id);

-- Workflow Step Run.
CREATE TABLE workflow_step_run (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    workflow_run_id uuid NOT NULL REFERENCES workflow_run(id) ON DELETE CASCADE,
    step_name text NOT NULL,
    state text NOT NULL,
    input_payload jsonb,
    output_payload jsonb,
    started_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz
);
CREATE INDEX workflow_step_run_tenant_idx ON workflow_step_run(tenant_id);

-- Target System Export: record of an export run.
CREATE TABLE target_system_export (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    engagement_id uuid NOT NULL REFERENCES engagement(id) ON DELETE CASCADE,
    target_system text NOT NULL,
    status text NOT NULL CHECK (status IN (
        'validating','refused','emitted','downloaded','archived')),
    blockers jsonb,
    s3_bucket text,
    s3_key text,
    exported_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX target_system_export_tenant_idx ON target_system_export(tenant_id);

-- Review Signoff.
CREATE TABLE review_signoff (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    engagement_id uuid NOT NULL REFERENCES engagement(id) ON DELETE CASCADE,
    artifact_type text NOT NULL,
    artifact_id uuid NOT NULL,
    signoff_level text NOT NULL CHECK (signoff_level IN (
        'preparer','first_reviewer','second_reviewer','partner')),
    signed_off_by_user_id uuid NOT NULL REFERENCES app_user(id) ON DELETE RESTRICT,
    signed_off_at timestamptz NOT NULL DEFAULT now(),
    notes text
);
CREATE INDEX review_signoff_tenant_idx ON review_signoff(tenant_id);

-- Validator Finding: output from the validator.
CREATE TABLE validator_finding (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    parse_result_id uuid REFERENCES parse_result(id) ON DELETE CASCADE,
    engagement_id uuid NOT NULL REFERENCES engagement(id) ON DELETE CASCADE,
    rule_id text NOT NULL,
    severity text NOT NULL CHECK (severity IN ('info','warning','error','blocker')),
    expected_value text,
    observed_value text,
    tolerance numeric(18,2),
    source_reference jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX validator_finding_tenant_idx ON validator_finding(tenant_id);
CREATE INDEX validator_finding_engagement_idx ON validator_finding(engagement_id);

-- Audit Log: immutable hash-chained event log.
-- NOTE: UPDATE and DELETE are revoked from app_user below; this is the
-- schema-level enforcement of R22.2 (tamper-evident append-only log).
CREATE TABLE audit_log_entry (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    actor_user_id uuid REFERENCES app_user(id) ON DELETE SET NULL,
    action text NOT NULL,
    resource_type text NOT NULL,
    resource_id uuid,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    prev_hash bytea NOT NULL,
    payload_hash bytea NOT NULL,
    sequence_number bigserial NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX audit_log_tenant_seq_idx
  ON audit_log_entry(tenant_id, sequence_number);
CREATE INDEX audit_log_resource_idx
  ON audit_log_entry(tenant_id, resource_type, resource_id);

-- Engagement Metering: usage tracking for billing / observability.
CREATE TABLE engagement_metering (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    engagement_id uuid NOT NULL REFERENCES engagement(id) ON DELETE CASCADE,
    metric_name text NOT NULL,
    metric_value numeric(18,4) NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX engagement_metering_tenant_idx ON engagement_metering(tenant_id);
"""


# --- Hash-chain trigger for audit_log_entry -----------------------------------

HASH_CHAIN_UP = """
-- Compute the hash chain on insert. Enforces:
--  * prev_hash == last inserted payload_hash for this tenant
--    (or 32 zero bytes if this is the first entry for the tenant)
--  * payload_hash == sha256(prev_hash || canonical payload || action ||
--    resource_type || resource_id || actor_user_id || sequence_number || occurred_at)
-- The trigger overwrites whatever the client set; the client's prev_hash /
-- payload_hash columns are ignored and replaced.
CREATE OR REPLACE FUNCTION audit_log_hash_chain_trigger()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    last_hash bytea;
    canonical text;
BEGIN
    -- Find the most-recent payload_hash for this tenant. Lock FOR UPDATE to
    -- serialize concurrent inserts within the same tenant — otherwise two
    -- simultaneous transactions could read the same last_hash and break
    -- the chain.
    SELECT payload_hash INTO last_hash
      FROM audit_log_entry
     WHERE tenant_id = NEW.tenant_id
     ORDER BY sequence_number DESC
     LIMIT 1
     FOR UPDATE;

    IF last_hash IS NULL THEN
        -- Genesis entry for this tenant
        last_hash := repeat('\\000', 32)::bytea;
    END IF;

    NEW.prev_hash := last_hash;

    -- Canonical representation. Order is fixed; null-safety matters.
    canonical := coalesce(encode(NEW.prev_hash, 'hex'), '')
               || '|' || NEW.action
               || '|' || NEW.resource_type
               || '|' || coalesce(NEW.resource_id::text, '')
               || '|' || coalesce(NEW.actor_user_id::text, '')
               || '|' || NEW.sequence_number::text
               || '|' || NEW.occurred_at::text
               || '|' || NEW.payload::text;

    NEW.payload_hash := digest(canonical, 'sha256');

    RETURN NEW;
END;
$$;
"""

# Note: ``digest()`` is from pgcrypto. pgcrypto isn't in pgserver's bundled
# extensions, so we ship an in-SQL SHA-256 via the built-in ``sha256()``
# function instead. PostgreSQL 11+ has ``sha256(bytea) -> bytea`` in core.
HASH_CHAIN_FIX = """
CREATE OR REPLACE FUNCTION audit_log_hash_chain_trigger()
RETURNS trigger LANGUAGE plpgsql AS $$
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

CREATE TRIGGER audit_log_hash_chain
BEFORE INSERT ON audit_log_entry
FOR EACH ROW EXECUTE FUNCTION audit_log_hash_chain_trigger();
"""


# --- Row-Level Security --------------------------------------------------------

# Every tenant-scoped table gets:
#  1. ENABLE ROW LEVEL SECURITY
#  2. FORCE ROW LEVEL SECURITY (so even the table owner must match the policy)
#  3. A single policy keyed on app_current_tenant_id() = tenant_id

TENANT_SCOPED_TABLES = [
    "firm",
    "app_user",
    "client",
    "engagement",
    "document",
    "parse_result",
    "account",
    "working_trial_balance_row",
    "journal_entry_adjustment",
    "journal_leg",
    "fixed_asset",
    "tax_line_mapping",
    "pbc_request",
    "workflow_run",
    "workflow_step_run",
    "target_system_export",
    "review_signoff",
    "validator_finding",
    "audit_log_entry",
    "engagement_metering",
]


def _rls_up_sql() -> str:
    parts: list[str] = []
    for t in TENANT_SCOPED_TABLES:
        parts.append(
            f"""
ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {t} FORCE ROW LEVEL SECURITY;
CREATE POLICY {t}_tenant_isolation ON {t}
    USING (tenant_id = app_current_tenant_id())
    WITH CHECK (tenant_id = app_current_tenant_id());
"""
        )
    # tenant table itself: different policy — platform_admin only, app_user
    # can read only its own row.
    parts.append(
        """
ALTER TABLE tenant ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_self_only ON tenant
    USING (id = app_current_tenant_id())
    WITH CHECK (id = app_current_tenant_id());
"""
    )
    return "\n".join(parts)


# --- GRANTs and REVOKEs --------------------------------------------------------

GRANTS_UP = """
-- app_user can operate on every tenant-scoped table. RLS then filters.
GRANT USAGE ON SCHEMA public TO app_user, platform_admin;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public
    TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public
    TO platform_admin;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public
    TO app_user, platform_admin;

-- Immutable audit log: app_user can only INSERT and SELECT. UPDATE and
-- DELETE are revoked, enforcing the append-only invariant at the DB level.
REVOKE UPDATE, DELETE, TRUNCATE ON audit_log_entry FROM app_user;
"""


# --- Migration functions ------------------------------------------------------

def upgrade() -> None:
    op.execute(ROLES_UP)
    op.execute(HELPER_UP)
    op.execute(TABLES_UP)
    op.execute(HASH_CHAIN_FIX)
    op.execute(_rls_up_sql())
    op.execute(GRANTS_UP)


def downgrade() -> None:
    # Drop RLS policies first, then tables, then helper + roles.
    tables = [*TENANT_SCOPED_TABLES, "tenant"]
    for t in tables:
        op.execute(f"DROP POLICY IF EXISTS {t}_tenant_isolation ON {t};")
    op.execute("DROP POLICY IF EXISTS tenant_self_only ON tenant;")
    op.execute("DROP TRIGGER IF EXISTS audit_log_hash_chain ON audit_log_entry;")
    op.execute("DROP FUNCTION IF EXISTS audit_log_hash_chain_trigger();")
    # Drop tables in reverse FK order.
    drop_order = [
        "engagement_metering",
        "audit_log_entry",
        "validator_finding",
        "review_signoff",
        "target_system_export",
        "workflow_step_run",
        "workflow_run",
        "pbc_request",
        "tax_line_mapping",
        "fixed_asset",
        "journal_leg",
        "journal_entry_adjustment",
        "working_trial_balance_row",
        "account",
        "parse_result",
        "document",
        "engagement",
        "client",
        "app_user",
        "firm",
        "tenant",
    ]
    for t in drop_order:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS app_current_tenant_id();")
    # Leave roles in place on downgrade; dropping them can fail if other
    # objects depend on them. Platform operators can drop manually.
