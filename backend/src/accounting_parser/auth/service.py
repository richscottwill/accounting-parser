"""High-level auth orchestration: signup + login flows.

Separates business logic from the FastAPI route shapes so it can be tested
without spinning a TestClient.

Signup flow (two-phase — the first admin registers a passkey atomically with
tenant creation):

1. ``begin_signup(firm_name, email, ptin)``:
   - Creates Tenant, Firm, Admin User rows (RLS-scoped transaction).
   - Provisions per-Tenant Cognito preparer pool + client-portal pool +
     KMS key alias.
   - Stores tenant-null signup_bootstrap challenge with the new user_id.
   - Returns WebAuthn registration options + a ``signup_token`` the client
     returns on complete.

2. ``complete_signup(signup_token, attestation_response)``:
   - Verifies the attestation, persists the credential.
   - Marks the Firm bootstrap complete, audit-logs both phases.
   - Issues a session JWT.

Login flow (one-phase — user already exists):

1. ``begin_login(email)`` — resolves user → tenant, returns assertion options.
2. ``complete_login(assertion_response)`` — verifies, issues JWT.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from jose import jwt
from sqlalchemy import text
from sqlalchemy.orm import Session

from accounting_parser.auth.audit import emit_audit_event
from accounting_parser.auth.cognito import (
    ensure_kms_alias,
    ensure_pool,
    create_cognito_user,
)
from accounting_parser.auth.session import issue_session_token
from accounting_parser.auth.webauthn import (
    RegistrationBegin,
    begin_registration,
    complete_registration,
    begin_authentication,
    complete_authentication,
)
from accounting_parser.config import Settings, get_settings
from accounting_parser.db.session import set_tenant_context

logger = logging.getLogger(__name__)


@dataclass
class SignupBeginResult:
    """Returned from begin_signup."""

    tenant_id: UUID
    firm_id: UUID
    user_id: UUID
    registration_options: dict[str, Any]
    signup_token: str  # short-lived JWT carrying tenant+user+challenge_id


@dataclass
class SignupCompleteResult:
    """Returned from complete_signup."""

    tenant_id: UUID
    firm_id: UUID
    user_id: UUID
    session_token: str


@dataclass
class LoginBeginResult:
    tenant_id: UUID
    user_id: UUID
    assertion_options: dict[str, Any]
    login_token: str


@dataclass
class LoginCompleteResult:
    tenant_id: UUID
    user_id: UUID
    session_token: str


def _mask_ptin(ptin: str | None) -> str | None:
    """Display-safe PTIN. PTINs are 'Pnnnnnnnn' format; show last 4 only."""
    if not ptin:
        return None
    if len(ptin) <= 4:
        return "****"
    return "****" + ptin[-4:]


def _issue_short_token(
    purpose: str,
    claims: dict[str, Any],
    *,
    settings: Settings,
    ttl_seconds: int = 600,
) -> str:
    """Mint a short-lived token carrying flow state between the begin/complete HTTP hops."""
    now = datetime.now(timezone.utc)
    payload = {
        **claims,
        "purpose": purpose,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, settings.session_secret, algorithm="HS256")


def _decode_short_token(token: str, expected_purpose: str, settings: Settings) -> dict[str, Any]:
    payload = jwt.decode(token, settings.session_secret, algorithms=["HS256"])
    if payload.get("purpose") != expected_purpose:
        raise ValueError(f"Token purpose mismatch: expected {expected_purpose}")
    return payload


def begin_signup(
    session: Session,
    *,
    firm_name: str,
    admin_email: str,
    admin_ptin: str | None,
    settings: Settings | None = None,
) -> SignupBeginResult:
    """Phase 1 of signup. Creates tenant+firm+admin, starts passkey registration."""
    settings = settings or get_settings()

    # Create tenant + firm + admin user rows. These go in as superuser /
    # platform_admin because there's no tenant context yet — the session
    # is the anonymous bootstrap session.
    tenant_id = uuid4()
    firm_id = uuid4()
    user_id = uuid4()
    kms_alias = f"alias/{tenant_id}"

    session.execute(
        text(
            """
            INSERT INTO tenant (id, name, kms_key_alias)
            VALUES (:id, :name, :alias)
            """
        ),
        {"id": str(tenant_id), "name": firm_name, "alias": kms_alias},
    )
    session.execute(
        text(
            """
            INSERT INTO firm (id, tenant_id, name, ptin)
            VALUES (:id, :tenant_id, :name, :ptin)
            """
        ),
        {
            "id": str(firm_id),
            "tenant_id": str(tenant_id),
            "name": firm_name,
            "ptin": admin_ptin,
        },
    )

    # Provision Cognito pools + KMS key before we write the app_user row
    # so failures fail atomically (bootstrap row inserts are rolled back).
    preparer_pool = ensure_pool(f"firm-{firm_id}-preparer", settings=settings)
    portal_pool = ensure_pool(f"firm-{firm_id}-portal", settings=settings)
    ensure_kms_alias(kms_alias, settings=settings)

    session.execute(
        text(
            """
            UPDATE firm
            SET cognito_preparer_pool_id = :pp,
                cognito_preparer_client_id = :pc,
                cognito_client_portal_pool_id = :cp,
                cognito_client_portal_client_id = :cc
            WHERE id = :id
            """
        ),
        {
            "id": str(firm_id),
            "pp": preparer_pool.pool_id,
            "pc": preparer_pool.client_id,
            "cp": portal_pool.pool_id,
            "cc": portal_pool.client_id,
        },
    )

    cognito_sub = create_cognito_user(preparer_pool.pool_id, admin_email, settings=settings)

    session.execute(
        text(
            """
            INSERT INTO app_user (
                id, tenant_id, firm_id, cognito_sub, email, role,
                ptin_masked, mfa_required
            )
            VALUES (
                :id, :tenant_id, :firm_id, :sub, :email,
                'firm_administrator', :ptin_masked, true
            )
            """
        ),
        {
            "id": str(user_id),
            "tenant_id": str(tenant_id),
            "firm_id": str(firm_id),
            "sub": cognito_sub,
            "email": admin_email,
            "ptin_masked": _mask_ptin(admin_ptin),
        },
    )

    # Set tenant context for the new rows so RLS-scoped inserts (audit,
    # challenges) succeed. The bootstrap session was previously
    # tenant-null; now we pin it to the just-created tenant.
    set_tenant_context(session, tenant_id)

    emit_audit_event(
        session,
        action="signup.tenant_bootstrap_begin",
        tenant_id=tenant_id,
        resource_type="firm",
        resource_id=firm_id,
        actor_user_id=user_id,
        payload={
            "firm_name": firm_name,
            "admin_email": admin_email,
            "ptin_masked": _mask_ptin(admin_ptin),
        },
    )

    # Start the WebAuthn registration ceremony.
    reg = begin_registration(
        session,
        tenant_id=tenant_id,
        user_id=user_id,
        user_email=admin_email,
        display_name=firm_name,
        settings=settings,
    )

    signup_token = _issue_short_token(
        "signup_complete",
        {
            "tenant_id": str(tenant_id),
            "firm_id": str(firm_id),
            "user_id": str(user_id),
            "challenge_id": str(reg.challenge_id),
            "email": admin_email,
        },
        settings=settings,
    )

    return SignupBeginResult(
        tenant_id=tenant_id,
        firm_id=firm_id,
        user_id=user_id,
        registration_options=reg.options,
        signup_token=signup_token,
    )


def complete_signup(
    session: Session,
    *,
    signup_token: str,
    client_data_json: bytes,
    attestation_object: bytes,
    settings: Settings | None = None,
) -> SignupCompleteResult:
    """Phase 2 of signup. Verify passkey, finalize firm bootstrap, issue session JWT."""
    settings = settings or get_settings()
    claims = _decode_short_token(signup_token, "signup_complete", settings)

    tenant_id = UUID(claims["tenant_id"])
    firm_id = UUID(claims["firm_id"])
    user_id = UUID(claims["user_id"])
    challenge_id = UUID(claims["challenge_id"])
    email = claims["email"]

    set_tenant_context(session, tenant_id)

    complete_registration(
        session,
        challenge_id=challenge_id,
        client_data_json=client_data_json,
        attestation_object=attestation_object,
        friendly_name="Primary passkey",
        settings=settings,
    )

    session.execute(
        text("UPDATE app_user SET last_login_at = now() WHERE id = :id"),
        {"id": str(user_id)},
    )

    emit_audit_event(
        session,
        action="signup.tenant_bootstrap_complete",
        tenant_id=tenant_id,
        resource_type="firm",
        resource_id=firm_id,
        actor_user_id=user_id,
        payload={"email": email},
    )

    session_token = issue_session_token(
        user_id=user_id,
        tenant_id=tenant_id,
        firm_id=firm_id,
        role="firm_administrator",
        email=email,
        settings=settings,
    )

    return SignupCompleteResult(
        tenant_id=tenant_id,
        firm_id=firm_id,
        user_id=user_id,
        session_token=session_token,
    )


def begin_login(
    session: Session,
    *,
    email: str,
    settings: Settings | None = None,
) -> LoginBeginResult:
    """Resolve user by email, return assertion options + short flow token."""
    settings = settings or get_settings()

    # Look up as platform_admin / bootstrap session (pre-auth); we scan across
    # tenants by email. In production this is rate-limited + under DDoS controls.
    row = session.execute(
        text(
            """
            SELECT id, tenant_id, firm_id, role, email
            FROM app_user
            WHERE email = :email
            LIMIT 1
            """
        ),
        {"email": email},
    ).mappings().first()
    if row is None:
        raise ValueError("No user with that email")

    tenant_id = UUID(str(row["tenant_id"]))
    user_id = UUID(str(row["id"]))

    set_tenant_context(session, tenant_id)

    auth = begin_authentication(
        session, tenant_id=tenant_id, user_id=user_id, settings=settings
    )

    login_token = _issue_short_token(
        "login_complete",
        {
            "tenant_id": str(tenant_id),
            "user_id": str(user_id),
            "firm_id": str(row["firm_id"]) if row["firm_id"] else None,
            "role": row["role"],
            "email": row["email"],
            "challenge_id": str(auth.challenge_id),
        },
        settings=settings,
    )

    return LoginBeginResult(
        tenant_id=tenant_id,
        user_id=user_id,
        assertion_options=auth.assertion_options if False else auth.options,  # keep attr compatible
        login_token=login_token,
    )


def complete_login(
    session: Session,
    *,
    login_token: str,
    credential_id_bytes: bytes,
    client_data_json: bytes,
    authenticator_data: bytes,
    signature: bytes,
    settings: Settings | None = None,
) -> LoginCompleteResult:
    """Verify assertion, issue session JWT."""
    settings = settings or get_settings()
    claims = _decode_short_token(login_token, "login_complete", settings)

    tenant_id = UUID(claims["tenant_id"])
    user_id = UUID(claims["user_id"])
    firm_id = UUID(claims["firm_id"]) if claims.get("firm_id") else None
    role = claims["role"]
    email = claims["email"]
    challenge_id = UUID(claims["challenge_id"])

    set_tenant_context(session, tenant_id)

    try:
        complete_authentication(
            session,
            challenge_id=challenge_id,
            credential_id_bytes=credential_id_bytes,
            client_data_json=client_data_json,
            authenticator_data=authenticator_data,
            signature=signature,
            settings=settings,
        )
    except Exception as e:
        emit_audit_event(
            session,
            action="auth.login_failed",
            tenant_id=tenant_id,
            resource_type="app_user",
            resource_id=user_id,
            payload={"email": email, "error": str(e)},
        )
        raise

    session.execute(
        text("UPDATE app_user SET last_login_at = now() WHERE id = :id"),
        {"id": str(user_id)},
    )

    emit_audit_event(
        session,
        action="auth.login",
        tenant_id=tenant_id,
        resource_type="app_user",
        resource_id=user_id,
        payload={"email": email, "role": role},
    )

    session_token = issue_session_token(
        user_id=user_id,
        tenant_id=tenant_id,
        firm_id=firm_id,
        role=role,
        email=email,
        settings=settings,
    )

    return LoginCompleteResult(
        tenant_id=tenant_id,
        user_id=user_id,
        session_token=session_token,
    )
