"""Task 5 auth foundation: webauthn_credential table + firm/user auth fields.

Extends the Task 3 schema with the pieces Task 5 needs:

- ``firm`` gets two Cognito user pool IDs (preparer pool + client-portal pool)
  and a KMS key alias reference surfaced from the parent tenant.
- ``app_user`` gains ``ptin_masked`` (display-safe last 4 of PTIN per
  Requirement 1.9 / 21.8), ``last_login_at``, ``mfa_required`` flag.
- New ``webauthn_credential`` table stores one row per registered passkey,
  scoped by tenant_id with RLS. Keyed on credential_id (the CredentialID
  the authenticator returned at registration). Public key is stored as
  COSE-encoded bytes.
- New ``auth_challenge`` table buffers short-lived WebAuthn ceremony
  challenges. TTL-expired challenges are swept by a scheduled job.

All new tables are tenant-scoped and carry RLS policies. ``audit_log_entry``
is untouched (already append-only from Task 3).

Revision ID: 20260506_0002
Revises: 20260505_0001
"""
from __future__ import annotations

from alembic import op

# Revision identifiers used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


UP_SQL = """
-- Firm extensions: Cognito pool IDs provisioned at signup, one per auth realm.
ALTER TABLE firm
    ADD COLUMN cognito_preparer_pool_id text,
    ADD COLUMN cognito_client_portal_pool_id text,
    ADD COLUMN cognito_preparer_client_id text,
    ADD COLUMN cognito_client_portal_client_id text;

-- App-user extensions: PTIN display (masked), last login, MFA required flag.
-- Unmasked PTIN lives only in the encrypted Cognito UserAttributes layer
-- (or in a future column-level-encrypted field). Per Requirement 21.8 the
-- application database stores only the display-safe masked form.
ALTER TABLE app_user
    ADD COLUMN ptin_masked text,
    ADD COLUMN last_login_at timestamptz,
    ADD COLUMN mfa_required boolean NOT NULL DEFAULT false;

-- WebAuthn (passkey) credential registry. One row per registered authenticator
-- per user. Multiple credentials per user are supported (user may have a
-- desktop passkey and a phone passkey).
CREATE TABLE webauthn_credential (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    user_id uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    credential_id bytea NOT NULL,
    public_key_cose bytea NOT NULL,
    sign_count bigint NOT NULL DEFAULT 0,
    aaguid uuid,
    transports text[],
    backup_eligible boolean NOT NULL DEFAULT false,
    backup_state boolean NOT NULL DEFAULT false,
    friendly_name text,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz,
    CONSTRAINT webauthn_credential_id_unique UNIQUE (credential_id)
);
CREATE INDEX webauthn_credential_tenant_idx ON webauthn_credential(tenant_id);
CREATE INDEX webauthn_credential_user_idx ON webauthn_credential(user_id);

-- Auth challenge scratchpad: short-lived WebAuthn challenges for both
-- registration and assertion. Challenges expire after 5 minutes; a
-- scheduled sweep (Task 15 observability / Task 8 deploy schedule)
-- deletes rows past TTL.
CREATE TABLE auth_challenge (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid REFERENCES tenant(id) ON DELETE CASCADE,
    user_id uuid REFERENCES app_user(id) ON DELETE CASCADE,
    purpose text NOT NULL CHECK (purpose IN (
        'registration','authentication','signup_bootstrap')),
    challenge_bytes bytea NOT NULL,
    rp_id text NOT NULL,
    origin text NOT NULL,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    consumed_at timestamptz
);
CREATE INDEX auth_challenge_tenant_idx ON auth_challenge(tenant_id);
CREATE INDEX auth_challenge_expires_idx ON auth_challenge(expires_at);

-- RLS: webauthn_credential is strictly tenant-scoped.
ALTER TABLE webauthn_credential ENABLE ROW LEVEL SECURITY;
ALTER TABLE webauthn_credential FORCE ROW LEVEL SECURITY;
CREATE POLICY webauthn_credential_tenant_isolation ON webauthn_credential
    USING (tenant_id = app_current_tenant_id());

-- RLS: auth_challenge may be tenant-null during the pre-signup bootstrap,
-- so the policy permits null tenant_id only for 'signup_bootstrap'.
ALTER TABLE auth_challenge ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_challenge FORCE ROW LEVEL SECURITY;
CREATE POLICY auth_challenge_tenant_isolation ON auth_challenge
    USING (
        tenant_id = app_current_tenant_id()
        OR (tenant_id IS NULL AND purpose = 'signup_bootstrap')
    );

-- Grant table privileges to app_user (SELECT/INSERT/UPDATE/DELETE only;
-- table-level revoke on audit_log_entry is handled in the Task 3 migration).
GRANT SELECT, INSERT, UPDATE, DELETE ON webauthn_credential TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON auth_challenge TO app_user;
"""


DOWN_SQL = """
DROP TABLE IF EXISTS auth_challenge;
DROP TABLE IF EXISTS webauthn_credential;
ALTER TABLE app_user
    DROP COLUMN IF EXISTS mfa_required,
    DROP COLUMN IF EXISTS last_login_at,
    DROP COLUMN IF EXISTS ptin_masked;
ALTER TABLE firm
    DROP COLUMN IF EXISTS cognito_client_portal_client_id,
    DROP COLUMN IF EXISTS cognito_preparer_client_id,
    DROP COLUMN IF EXISTS cognito_client_portal_pool_id,
    DROP COLUMN IF EXISTS cognito_preparer_pool_id;
"""


def upgrade() -> None:
    op.execute(UP_SQL)


def downgrade() -> None:
    op.execute(DOWN_SQL)
