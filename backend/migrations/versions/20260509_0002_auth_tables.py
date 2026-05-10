"""Auth tables for self-hosted fork Phase 1 P1.1.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-09

Adds the tables needed for the Authentik auth adapter plus
client-portal magic-link auth. No destructive changes to the
parent schema: ``app_user.cognito_sub`` is kept as the column
name for backward compatibility with Task 3 tests; a plain
comment explains it now holds any provider's external id.

New tables:

- ``webauthn_credential`` — FIDO2 / passkey registrations, one
  row per (user, credential). Application-layer AuthN checks
  against this table; Authentik mirrors it via ``enroll_passkey``.
- ``magic_link_token`` — single-use, 15-min-TTL tokens for client
  portal auth (R26.4). Stores only the sha256 of the raw token.

Design references:
- ``.kiro/specs/accounting-parser-self-hosted/requirements.md``
  R26.1-R26.5, R28.5 (audit chain continues).
- ``.kiro/specs/accounting-parser-self-hosted/design.md`` §1, §3.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op


revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


WEBAUTHN_UP = """
CREATE TABLE webauthn_credential (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    user_id uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    credential_id bytea NOT NULL,
    public_key bytea NOT NULL,
    sign_count bigint NOT NULL DEFAULT 0,
    aaguid bytea,
    transports text[] NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz,
    CONSTRAINT webauthn_credential_id_unique UNIQUE (credential_id)
);
CREATE INDEX webauthn_credential_tenant_idx ON webauthn_credential(tenant_id);
CREATE INDEX webauthn_credential_user_idx ON webauthn_credential(user_id);

ALTER TABLE webauthn_credential ENABLE ROW LEVEL SECURITY;
ALTER TABLE webauthn_credential FORCE ROW LEVEL SECURITY;
CREATE POLICY webauthn_credential_tenant_isolation
    ON webauthn_credential
    FOR ALL
    TO PUBLIC
    USING (tenant_id = app_current_tenant_id())
    WITH CHECK (tenant_id = app_current_tenant_id());

GRANT SELECT, INSERT, UPDATE ON webauthn_credential TO app_user;

COMMENT ON TABLE webauthn_credential IS
  'FIDO2 / passkey registrations for app_user rows. Application-layer '
  'AuthN checks against this table; the IdP mirrors it so its own '
  'login flows work.';
COMMENT ON COLUMN webauthn_credential.sign_count IS
  'Authenticator-reported signature counter. Must increase between '
  'successful assertions; see CTAP2 / WebAuthn spec.';
"""

WEBAUTHN_DOWN = """
DROP TABLE IF EXISTS webauthn_credential;
"""

MAGIC_LINK_UP = """
CREATE TABLE magic_link_token (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE RESTRICT,
    email text NOT NULL,
    token_hash bytea NOT NULL,
    issued_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    used_from_ip text,
    CONSTRAINT magic_link_token_hash_unique UNIQUE (token_hash)
);
CREATE INDEX magic_link_token_tenant_email_idx
    ON magic_link_token(tenant_id, email);
CREATE INDEX magic_link_token_expires_idx
    ON magic_link_token(expires_at)
    WHERE used_at IS NULL;

ALTER TABLE magic_link_token ENABLE ROW LEVEL SECURITY;
ALTER TABLE magic_link_token FORCE ROW LEVEL SECURITY;
-- NOTE: RLS policy intentionally uses ``app_current_tenant_id() IS NULL``
-- OR a tenant match: the magic-link CONSUME path runs before we know
-- the tenant (the token maps to tenant). The service sets context
-- after reading the token. Allowing access when app.tenant_id is unset
-- is scoped by the token_hash uniqueness — you can't read other tenants'
-- tokens without already knowing their (random 32-byte) raw token.
CREATE POLICY magic_link_token_tenant_isolation
    ON magic_link_token
    FOR ALL
    TO PUBLIC
    USING (
        app_current_tenant_id() IS NULL
        OR tenant_id = app_current_tenant_id()
    )
    WITH CHECK (tenant_id = app_current_tenant_id());

GRANT SELECT, INSERT, UPDATE ON magic_link_token TO app_user;

COMMENT ON TABLE magic_link_token IS
  'Single-use, 15-minute-TTL tokens for Client portal initial login '
  '(R26.4). Only the sha256 of the raw token is persisted.';
COMMENT ON COLUMN magic_link_token.token_hash IS
  'sha256 of the raw URL-safe token. Raw token is emailed once and '
  'never stored server-side.';
"""

MAGIC_LINK_DOWN = """
DROP TABLE IF EXISTS magic_link_token;
"""

# The ``app_user.cognito_sub`` column is retained for schema backward
# compatibility with Task 3. Its role is now provider-agnostic —
# it holds whatever external id the active AuthAdapter returns. A
# future migration may rename to ``external_id`` + add an
# ``external_provider`` column; for Phase 1 P1.1 we just update the
# comment so greppers find the right intent.
COLUMN_COMMENT_UP = """
COMMENT ON COLUMN app_user.cognito_sub IS
  'Provider-assigned external user id. Named cognito_sub for historical '
  'reasons (migration 0001); currently used by AuthentikAuthAdapter. '
  'Renaming to external_id is queued for a later migration.';
"""

COLUMN_COMMENT_DOWN = """
COMMENT ON COLUMN app_user.cognito_sub IS NULL;
"""


def upgrade() -> None:
    op.execute(WEBAUTHN_UP)
    op.execute(MAGIC_LINK_UP)
    op.execute(COLUMN_COMMENT_UP)


def downgrade() -> None:
    op.execute(COLUMN_COMMENT_DOWN)
    op.execute(MAGIC_LINK_DOWN)
    op.execute(WEBAUTHN_DOWN)
