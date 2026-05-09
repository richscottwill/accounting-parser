"""AuthService — business logic layered on top of ``AuthAdapter``.

The adapter talks to Authentik. The service talks to our database
and enforces the self-hosted fork's policy rules:

- R25.3: exactly one Firm_Instance on a given installation.
- R26.2: passkey-first signup; password fallback is opt-in per user.
- R28.2: per-Client DEK derivation happens at ingest, not here, but
  the master-key material used by the HKDF is owned by the KMS
  adapter (P1.3); this service only deals in identity primitives.

### Why a service layer at all

Routes would otherwise reach into the adapter, the database, and
the audit helpers directly — that couples HTTP concerns to DB
concerns, which makes testing impossible without a running UI. The
service layer is testable against an in-memory sqlite-alike session
factory (we use the existing pgserver fixtures) and stubs of the
adapter (see ``tests/auth/test_signup.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from accounting_parser.auth.adapter import (
    AuthAdapter,
    AuthenticatedUser,
    PasskeyCredential,
    UserRole,
)
from accounting_parser.auth.audit import AuthAction, append_auth_event
from accounting_parser.auth.magic_link import (
    InvalidMagicLinkError,
    IssuedMagicLink,
    compute_token_hash,
    default_expiry,
    generate_token,
)


class FirmAlreadyProvisionedError(RuntimeError):
    """Raised when signup attempts to create a second firm.

    Per R25.3, a single installation serves exactly one firm. This
    is not a validation error the user can fix; it requires a fresh
    install. Route handlers return 409 Conflict with a link to
    docs/install-guide.md.
    """


class PasskeyEnrollmentError(RuntimeError):
    """Raised when passkey enrollment fails at the application layer.

    Distinct from ``PasskeyAssertionError`` which is for authentication
    (login) failures. Enrollment failures surface at signup and at
    explicit "add another passkey" routes.
    """


# Re-export magic-link errors so callers can catch them via this module
__all__ = [
    "AuthService",
    "FirmAlreadyProvisionedError",
    "InvalidMagicLinkError",
    "PasskeyEnrollmentError",
    "ProvisionedFirm",
]


@dataclass(frozen=True)
class ProvisionedFirm:
    """Return value of ``AuthService.bootstrap_firm``.

    The caller (signup route) uses these ids to emit a "next step"
    response pointing the browser at the passkey-enrollment UI.
    """

    tenant_id: UUID
    firm_id: UUID
    firm_administrator_id: UUID
    external_id: str


class AuthService:
    """Policy layer. Stateless except for its injected adapter."""

    def __init__(self, *, adapter: AuthAdapter) -> None:
        self.adapter = adapter

    # ---- Firm bootstrap -------------------------------------------

    async def bootstrap_firm(
        self,
        session: Session,
        *,
        firm_name: str,
        principal_email: str,
        principal_display_name: str,
        tenant_name: str | None = None,
    ) -> ProvisionedFirm:
        """Provision the single Firm_Instance for this install.

        Order of operations:

        1. Acquire an advisory lock so concurrent signup attempts
           serialize. If ``pg_try_advisory_xact_lock`` fails we
           treat the signup as already-in-progress and reject.
        2. Check ``firm`` table; if any row exists, raise
           ``FirmAlreadyProvisionedError`` (R25.3).
        3. Insert ``tenant``, then ``firm``, then the Firm_Administrator
           ``app_user``. The adapter creates the IdP user in the
           middle — if the IdP call fails, the whole transaction
           rolls back so we don't orphan a DB row.
        4. Emit an ``auth.signup.succeeded`` audit event.
        """
        # Acquire the lock. We use a constant key so every signup
        # attempt contends for the same lock even before we know
        # the tenant_id. Key is an arbitrary chosen 64-bit integer
        # representing "firm bootstrap" — any unique int works.
        locked = session.execute(
            text("SELECT pg_try_advisory_xact_lock(7438921470201)")
        ).scalar_one()
        if not locked:
            # Concurrent bootstrap. Treat as "already in progress";
            # the other transaction's outcome determines state.
            raise FirmAlreadyProvisionedError(
                "another signup is in progress; retry after it completes"
            )

        existing = session.execute(text("SELECT count(*) FROM firm")).scalar_one()
        if existing and existing > 0:
            # R25.3: audit the rejection before raising so ops visibility
            # doesn't depend on exception handling at the route layer.
            first_tenant = session.execute(text("SELECT id FROM tenant LIMIT 1")).scalar_one()
            append_auth_event(
                session,
                tenant_id=first_tenant,
                actor_user_id=None,
                action=AuthAction.SIGNUP_REJECTED,
                payload={
                    "reason": "firm_already_provisioned",
                    "attempted_firm_name": firm_name,
                    "attempted_email": principal_email,
                },
            )
            raise FirmAlreadyProvisionedError(
                "This installation already has a Firm_Instance; a single "
                "installation serves exactly one firm (R25.3). For a second "
                "firm, run a separate installation. See docs/install-guide.md."
            )

        tenant_id = uuid4()
        firm_id = uuid4()
        user_id = uuid4()

        # Insert tenant first (RLS policies on firm/app_user require it).
        session.execute(
            text("INSERT INTO tenant (id, name) VALUES (:id, :name)"),
            {"id": str(tenant_id), "name": tenant_name or firm_name},
        )

        # set_tenant_context for subsequent inserts so RLS allows them
        # when running as app_user. When the service is invoked from
        # the installer (as platform_admin), this is a no-op but still
        # correct.
        session.execute(
            text("SELECT set_config('app.tenant_id', :tid, false)"),
            {"tid": str(tenant_id)},
        )

        session.execute(
            text(
                """
                INSERT INTO firm (id, tenant_id, name)
                VALUES (:id, :tid, :name)
                """
            ),
            {"id": str(firm_id), "tid": str(tenant_id), "name": firm_name},
        )

        # Create the IdP-side user first. If this fails, the outer
        # transaction rolls back and no DB artifacts are left.
        external_id = await self.adapter.create_user(
            tenant_id=tenant_id,
            firm_id=firm_id,
            email=principal_email,
            role=UserRole.FIRM_ADMINISTRATOR,
            display_name=principal_display_name,
        )

        session.execute(
            text(
                """
                INSERT INTO app_user
                    (id, tenant_id, firm_id, cognito_sub, email, role)
                VALUES
                    (:id, :tid, :fid, :sub, :email, :role)
                """
            ),
            {
                "id": str(user_id),
                "tid": str(tenant_id),
                "fid": str(firm_id),
                # Column is still named ``cognito_sub`` in the schema
                # (migration 0001). Migration 0002 renames it to
                # ``external_id``; until that migration ships this
                # service writes into the old column name.
                "sub": external_id,
                "email": principal_email,
                "role": UserRole.FIRM_ADMINISTRATOR.value,
            },
        )

        append_auth_event(
            session,
            tenant_id=tenant_id,
            actor_user_id=user_id,
            action=AuthAction.SIGNUP_SUCCEEDED,
            resource_id=user_id,
            payload={
                "firm_name": firm_name,
                "email": principal_email,
                "provider": self.adapter.provider.value,
            },
        )

        return ProvisionedFirm(
            tenant_id=tenant_id,
            firm_id=firm_id,
            firm_administrator_id=user_id,
            external_id=external_id,
        )

    # ---- Passkey enrollment --------------------------------------

    async def complete_passkey_enrollment(
        self,
        session: Session,
        *,
        user: AuthenticatedUser,
        credential: PasskeyCredential,
    ) -> None:
        """Persist a verified passkey and notify the IdP.

        Caller has already verified the WebAuthn attestation via
        ``webauthn.verify_registration``. This function:

        1. Inserts the credential into ``webauthn_credential``.
        2. Calls ``adapter.enroll_passkey`` to notify the IdP.
           If this fails, the DB insert is still preserved (the
           local credential works; Authentik-side failure is a
           follow-up retry via a background job). We audit-log
           both the success and the IdP-notify failure.
        3. Emits ``auth.passkey.enrollment.succeeded``.

        Rationale for not rolling back on IdP failure: losing the
        local passkey because Authentik was momentarily unreachable
        would brick the firm's signup. The user can log in via the
        local credential on next request; a sync job reconciles
        Authentik's view.
        """
        # Insert the local credential row.
        session.execute(
            text(
                """
                INSERT INTO webauthn_credential
                    (id, tenant_id, user_id, credential_id, public_key,
                     sign_count, aaguid, transports, created_at)
                VALUES
                    (gen_random_uuid(), :tid, :uid, :cid, :pk,
                     :sc, :aaguid, :transports, now())
                """
            ),
            {
                "tid": str(user.tenant_id),
                "uid": str(user.user_id),
                "cid": credential.credential_id,
                "pk": credential.public_key,
                "sc": credential.sign_count,
                "aaguid": credential.aaguid,
                "transports": list(credential.transports),
            },
        )

        # Notify IdP; log success or failure, never raise past here.
        idp_ok = True
        idp_error: str | None = None
        try:
            await self.adapter.enroll_passkey(
                external_id=user.external_id,
                credential=credential,
            )
        except Exception as e:  # noqa: BLE001 — we intentionally trap
            idp_ok = False
            idp_error = type(e).__name__

        append_auth_event(
            session,
            tenant_id=user.tenant_id,
            actor_user_id=user.user_id,
            action=AuthAction.PASSKEY_ENROLLMENT_SUCCEEDED,
            resource_id=user.user_id,
            payload={
                "provider": self.adapter.provider.value,
                "idp_sync_ok": idp_ok,
                "idp_error": idp_error,
            },
        )

    # ---- Magic link -----------------------------------------------

    async def issue_magic_link(
        self,
        session: Session,
        *,
        tenant_id: UUID,
        email: str,
    ) -> IssuedMagicLink:
        """Generate and persist a magic-link token (R26.4).

        The returned ``IssuedMagicLink.raw_token`` is given to the
        email sender exactly once; it is not persisted anywhere
        locally. The sha256 hash is what lives in the database.
        """
        raw, digest = generate_token()
        expires_at = default_expiry()

        session.execute(
            text(
                """
                INSERT INTO magic_link_token
                    (id, tenant_id, email, token_hash, issued_at, expires_at)
                VALUES
                    (gen_random_uuid(), :tid, :email, :hash, now(), :exp)
                """
            ),
            {
                "tid": str(tenant_id),
                "email": email,
                "hash": digest,
                "exp": expires_at,
            },
        )

        append_auth_event(
            session,
            tenant_id=tenant_id,
            actor_user_id=None,
            action=AuthAction.MAGIC_LINK_ISSUED,
            payload={"email": email, "expires_at": expires_at.isoformat()},
        )

        return IssuedMagicLink(
            raw_token=raw,
            token_hash=digest,
            expires_at=expires_at,
            email=email,
            tenant_id=tenant_id,
        )

    async def consume_magic_link(
        self,
        session: Session,
        *,
        raw_token: str,
    ) -> tuple[UUID, str]:
        """Mark a magic-link token used and return (tenant_id, email).

        Raises ``InvalidMagicLinkError`` for: unknown, expired, used.
        The single-error shape prevents attackers from distinguishing
        "token doesn't exist" from "token expired" from "token used".
        """
        digest = compute_token_hash(raw_token)
        now = datetime.now(UTC)

        # Atomic update: mark used only if not previously used and
        # not expired. The RETURNING clause gives us the row values
        # if the update matched.
        row = session.execute(
            text(
                """
                UPDATE magic_link_token
                SET used_at = :now
                WHERE token_hash = :hash
                  AND used_at IS NULL
                  AND expires_at > :now
                RETURNING tenant_id, email
                """
            ),
            {"now": now, "hash": digest},
        ).first()

        if row is None:
            # Capture audit on the tenant of record if we can find one;
            # otherwise use the tenant table's first row. The rejection
            # still needs to live in an audit log somewhere.
            #
            # We commit the audit event in its own savepoint so the
            # outer transaction's rollback (triggered by raising
            # ``InvalidMagicLinkError``) doesn't discard it. The
            # rejection must be recorded even though the caller treats
            # the whole operation as failed.
            fallback_tenant = session.execute(
                text("SELECT id FROM tenant LIMIT 1")
            ).scalar_one_or_none()
            if fallback_tenant:
                with session.begin_nested():
                    append_auth_event(
                        session,
                        tenant_id=fallback_tenant,
                        actor_user_id=None,
                        action=AuthAction.MAGIC_LINK_REJECTED,
                        payload={"reason": "invalid_or_expired_or_used"},
                    )
                # Commit the outer transaction's audit row without
                # committing anything else. Because the service's
                # only DB operation in the failure path is this audit
                # event, this commit is safe — there's nothing else
                # to preserve or discard.
                session.commit()
            raise InvalidMagicLinkError("invalid, expired, or already-used magic link")

        tenant_id = UUID(str(row[0]))
        email = str(row[1])
        append_auth_event(
            session,
            tenant_id=tenant_id,
            actor_user_id=None,
            action=AuthAction.MAGIC_LINK_CONSUMED,
            payload={"email": email},
        )
        return tenant_id, email

    # ---- Session lifecycle ----------------------------------------

    async def revoke_session(
        self,
        session: Session,
        *,
        user: AuthenticatedUser,
        token: str,
    ) -> None:
        """Revoke a session at the IdP and record the event.

        Best-effort at the adapter; always audits locally.
        """
        # contextlib.suppress wraps the adapter call so a transient
        # IdP failure can't prevent the audit entry from landing.
        # Logging the caught exception happens inside the adapter;
        # the service layer intentionally does not re-log it.
        from contextlib import suppress

        with suppress(Exception):
            await self.adapter.invalidate_session(token=token)
        append_auth_event(
            session,
            tenant_id=user.tenant_id,
            actor_user_id=user.user_id,
            action=AuthAction.SESSION_REVOKED,
            payload={"provider": self.adapter.provider.value},
        )

    async def record_login_success(
        self,
        session: Session,
        *,
        user: AuthenticatedUser,
    ) -> None:
        """Audit a successful login after passkey assertion."""
        append_auth_event(
            session,
            tenant_id=user.tenant_id,
            actor_user_id=user.user_id,
            action=AuthAction.LOGIN_SUCCEEDED,
            payload={"provider": self.adapter.provider.value},
        )

    async def record_login_failure(
        self,
        session: Session,
        *,
        tenant_id: UUID,
        attempted_email: str,
        reason: str,
    ) -> None:
        """Audit a failed login.

        ``reason`` must be a short, non-secret tag like
        ``passkey_assertion_failed`` or ``user_not_found``. Do not
        include the raw assertion or challenge.
        """
        append_auth_event(
            session,
            tenant_id=tenant_id,
            actor_user_id=None,
            action=AuthAction.LOGIN_FAILED,
            payload={
                "attempted_email": attempted_email,
                "reason": reason,
                "provider": self.adapter.provider.value,
            },
        )
