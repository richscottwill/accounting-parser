"""Authentication and tenant provisioning subsystem.

Implements Task 5 of the Accounting Document Parser:

- Cognito user pool provisioning (preparer pool + client-portal pool) via
  LocalStack in dev, AWS in prod. Two separate pools per Requirement 21.
- WebAuthn (passkey) registration and assertion via the ``fido2`` library
  for preparers and firm administrators (Requirement 21.6).
- FastAPI middleware that extracts the session JWT, resolves user → tenant,
  sets ``app.tenant_id`` on the DB session for every request
  (Requirement 1.10 enforcement at the HTTP/app layer, complementing the
  Postgres RLS policies from Task 3).
- Firm self-signup flow that bootstraps a Tenant + Firm + first
  Firm_Administrator user, provisions a per-Tenant KMS key alias, and
  registers the administrator's first passkey.

Every authentication event is audit-logged through the chained append-only
``audit_log_entry`` table from Task 3.
"""
# Opt in to python-fido2's JSON-friendly mapping (the non-deprecated path).
# Must be set before any fido2 data class is built or accessed as a Mapping.
import fido2.features  # noqa: E402

fido2.features.webauthn_json_mapping.enabled = True  # type: ignore[attr-defined]
