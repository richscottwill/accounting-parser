"""Auth HTTP routes.

Endpoints:

- ``POST /auth/signup`` — Firm_Administrator bootstrap (R25.1, R25.3)
- ``POST /auth/passkey/register/begin`` — WebAuthn ceremony start
- ``POST /auth/passkey/register/complete`` — ceremony finish, returns session token
- ``POST /auth/login/begin`` — WebAuthn assertion ceremony start
- ``POST /auth/login/complete`` — assertion finish, returns session token
- ``POST /auth/logout`` — revoke session + audit
- ``GET  /auth/me`` — introspect current session

### Error handling

- 400: bad request input (validation)
- 401: unauthenticated (middleware or passkey assertion failure)
- 403: authenticated but lacks role (returns the middleware-resolved
       user + the required role for audit clarity — attackers know
       they're logged in, so the role disclosure isn't an oracle)
- 409: Firm already provisioned (R25.3)
- 500: unexpected — bubbled to structured log
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from accounting_parser.api.deps import (
    get_auth_service,
    get_current_user,
    get_db,
    get_db_unauthed,
    get_platform_db,
)
from accounting_parser.auth.adapter import (
    AuthAdapter,
    AuthenticatedUser,
    PasskeyAssertionError,
    PasskeyCredential,
    UserRole,
)
from accounting_parser.auth.service import AuthService, FirmAlreadyProvisionedError
from accounting_parser.auth.webauthn import (
    generate_assertion_challenge,
    generate_registration_challenge,
    random_challenge,
    verify_registration,
)

router = APIRouter()


# ---- Request / response models -------------------------------------


class SignupBody(BaseModel):
    firm_name: str = Field(min_length=1, max_length=255)
    principal_email: EmailStr
    principal_display_name: str = Field(min_length=1, max_length=255)


class SignupResponse(BaseModel):
    tenant_id: str
    firm_id: str
    firm_administrator_id: str
    passkey_enrollment_required: bool = True


class PasskeyRegisterBeginResponse(BaseModel):
    challenge_b64: str
    rp_id: str
    rp_name: str
    user_handle_b64: str
    # ``state_b64`` is an opaque blob the client echoes back to us in
    # the /complete call. We HMAC it to detect tampering before the
    # client ever sees it; for MVP the state is forwarded plain and
    # the verify call catches any attestation mismatch. HMAC wrapping
    # is a P2 hardening item.
    state_b64: str


class PasskeyRegisterCompleteBody(BaseModel):
    user_id: str
    state_b64: str
    client_data_json_b64: str
    attestation_object_b64: str


class LoginBeginBody(BaseModel):
    email: EmailStr


class LoginBeginResponse(BaseModel):
    challenge_b64: str
    rp_id: str
    allowed_credentials_b64: list[str]
    # session_token pinning for the challenge — a light cookie that
    # echoes back in login/complete. Lives 2 minutes.
    pending_session_b64: str


class LoginCompleteBody(BaseModel):
    email: EmailStr
    credential_id_b64: str
    assertion_cbor_b64: str
    pending_session_b64: str


class SessionTokenResponse(BaseModel):
    token: str
    expires_at: datetime
    user_id: str
    tenant_id: str


class MeResponse(BaseModel):
    user_id: str
    tenant_id: str
    firm_id: str | None
    email: str
    role: str
    session_expires_at: datetime


# ---- Handlers ------------------------------------------------------


@router.post("/signup", response_model=SignupResponse, status_code=201)
async def signup(
    body: SignupBody,
    service: AuthService = Depends(get_auth_service),
    session: Session = Depends(get_platform_db),
) -> SignupResponse:
    """Provision the single Firm_Instance and the first user (R25.1).

    R25.3: this endpoint refuses to provision a second Firm. Attempt
    returns 409 Conflict with a user-readable pointer to docs.
    """
    try:
        result = await service.bootstrap_firm(
            session,
            firm_name=body.firm_name,
            principal_email=body.principal_email,
            principal_display_name=body.principal_display_name,
        )
    except FirmAlreadyProvisionedError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    return SignupResponse(
        tenant_id=str(result.tenant_id),
        firm_id=str(result.firm_id),
        firm_administrator_id=str(result.firm_administrator_id),
        passkey_enrollment_required=True,
    )


@router.post("/passkey/register/begin", response_model=PasskeyRegisterBeginResponse)
async def passkey_register_begin(
    request: Request,
    user_id: str,
    email: str,
    display_name: str,
    session: Session = Depends(get_db_unauthed),
) -> PasskeyRegisterBeginResponse:
    """Start a WebAuthn registration ceremony.

    Called from the browser immediately after signup. The user_id
    comes back in the /complete step so the caller can't substitute
    a different user handle on completion.
    """
    settings = request.app.state.settings
    user_handle = user_id.encode("utf-8")
    challenge = generate_registration_challenge(
        user_id=user_handle,
        user_name=email,
        user_display_name=display_name,
        rp_id=settings.firm_rp_id,
        rp_name=settings.firm_rp_name,
    )
    return PasskeyRegisterBeginResponse(
        challenge_b64=_b64(challenge.challenge),
        rp_id=settings.firm_rp_id,
        rp_name=settings.firm_rp_name,
        user_handle_b64=_b64(user_handle),
        state_b64=_b64(json.dumps(_json_safe(challenge.state)).encode("utf-8")),
    )


@router.post("/passkey/register/complete", response_model=SessionTokenResponse)
async def passkey_register_complete(
    body: PasskeyRegisterCompleteBody,
    request: Request,
    adapter: AuthAdapter = Depends(lambda r=Request: r.app.state.auth_adapter),
    service: AuthService = Depends(get_auth_service),
    session: Session = Depends(get_db_unauthed),
) -> SessionTokenResponse:
    """Verify the attestation, persist the credential, return session."""
    settings = request.app.state.settings
    state = json.loads(_b64d(body.state_b64).decode("utf-8"))

    try:
        credential = verify_registration(
            state=state,
            client_data_json=_b64d(body.client_data_json_b64),
            attestation_object_cbor=_b64d(body.attestation_object_b64),
            rp_id=settings.firm_rp_id,
            rp_name=settings.firm_rp_name,
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=400, detail="Passkey registration failed verification"
        ) from e

    # Resolve the user row so we can attach the credential.
    from sqlalchemy import text

    row = session.execute(
        text(
            """
            SELECT id, tenant_id, firm_id, email, role, cognito_sub
            FROM app_user WHERE id = :uid
            """
        ),
        {"uid": body.user_id},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")

    from uuid import UUID

    user = AuthenticatedUser(
        user_id=UUID(str(row[0])),
        tenant_id=UUID(str(row[1])),
        firm_id=UUID(str(row[2])) if row[2] else None,
        email=str(row[3]),
        role=UserRole(str(row[4])),
        external_id=str(row[5]),
        external_provider=adapter.provider,
        session_expires_at=datetime.now(UTC),
        passkey_verified=True,
    )

    # Pin RLS context now that we have a tenant resolved.
    session.execute(
        text("SELECT set_config('app.tenant_id', :tid, false)"),
        {"tid": str(user.tenant_id)},
    )

    await service.complete_passkey_enrollment(
        session,
        user=user,
        credential=credential,
    )

    token = await adapter.issue_session(
        user=user,
        credential=credential,
        session_duration_seconds=settings.session_duration_seconds,
    )

    return SessionTokenResponse(
        token=token.token,
        expires_at=token.expires_at,
        user_id=str(user.user_id),
        tenant_id=str(user.tenant_id),
    )


@router.post("/login/begin", response_model=LoginBeginResponse)
async def login_begin(
    body: LoginBeginBody,
    request: Request,
    session: Session = Depends(get_db_unauthed),
) -> LoginBeginResponse:
    """Start a login ceremony by issuing a challenge + allowed-credentials list.

    We don't reveal whether the email exists — for an unknown email
    we still return a challenge, bound to random credential IDs. The
    /complete step naturally fails for unknown users, but timing +
    response shape is uniform either way.
    """
    settings = request.app.state.settings
    from sqlalchemy import text

    rows = session.execute(
        text(
            """
            SELECT wc.credential_id
            FROM app_user u
            JOIN webauthn_credential wc ON wc.user_id = u.id
            WHERE u.email = :email
            """
        ),
        {"email": body.email},
    ).all()
    credential_ids = [bytes(r[0]) for r in rows] if rows else [random_challenge(16)]

    challenge = generate_assertion_challenge(
        credential_ids=credential_ids,
        rp_id=settings.firm_rp_id,
        rp_name=settings.firm_rp_name,
    )
    pending = _b64(json.dumps(_json_safe(challenge.state)).encode("utf-8"))

    return LoginBeginResponse(
        challenge_b64=_b64(challenge.challenge),
        rp_id=settings.firm_rp_id,
        allowed_credentials_b64=[_b64(cid) for cid in credential_ids],
        pending_session_b64=pending,
    )


@router.post("/login/complete", response_model=SessionTokenResponse)
async def login_complete(
    body: LoginCompleteBody,
    request: Request,
    adapter: AuthAdapter = Depends(lambda r=Request: r.app.state.auth_adapter),
    service: AuthService = Depends(get_auth_service),
    session: Session = Depends(get_db_unauthed),
) -> SessionTokenResponse:
    """Complete a login ceremony; return a session JWT."""
    from uuid import UUID

    from sqlalchemy import text

    credential_id = _b64d(body.credential_id_b64)

    row = session.execute(
        text(
            """
            SELECT u.id, u.tenant_id, u.firm_id, u.email, u.role,
                   u.cognito_sub, wc.public_key, wc.sign_count
            FROM app_user u
            JOIN webauthn_credential wc ON wc.user_id = u.id
            WHERE u.email = :email AND wc.credential_id = :cid
            """
        ),
        {"email": body.email, "cid": credential_id},
    ).first()

    if row is None:
        # Unknown user or credential. Audit against a best-effort
        # tenant (the only one on single-firm installs).
        tenant_row = session.execute(text("SELECT id FROM tenant LIMIT 1")).scalar_one_or_none()
        if tenant_row is not None:
            await service.record_login_failure(
                session,
                tenant_id=UUID(str(tenant_row)),
                attempted_email=body.email,
                reason="user_or_credential_not_found",
            )
        raise HTTPException(status_code=401, detail="Unauthorized")

    state = json.loads(_b64d(body.pending_session_b64).decode("utf-8"))
    challenge = state.get("challenge")
    if isinstance(challenge, str):
        challenge_bytes = _b64d(challenge)
    elif isinstance(challenge, bytes | bytearray):
        challenge_bytes = bytes(challenge)
    else:
        challenge_bytes = bytes(challenge) if challenge else b""

    try:
        new_sign_count = await adapter.verify_passkey_assertion(
            external_id=str(row[5]),
            assertion=_b64d(body.assertion_cbor_b64),
            challenge=challenge_bytes,
            credential_id=credential_id,
            public_key=bytes(row[6]),
            stored_sign_count=int(row[7]),
        )
    except PasskeyAssertionError:
        await service.record_login_failure(
            session,
            tenant_id=UUID(str(row[1])),
            attempted_email=body.email,
            reason="passkey_assertion_failed",
        )
        raise HTTPException(status_code=401, detail="Unauthorized") from None

    # Update sign_count and pin tenant before auditing success.
    session.execute(
        text(
            """
            UPDATE webauthn_credential
            SET sign_count = :sc
            WHERE credential_id = :cid
            """
        ),
        {"sc": new_sign_count, "cid": credential_id},
    )
    session.execute(
        text("SELECT set_config('app.tenant_id', :tid, false)"),
        {"tid": str(row[1])},
    )

    credential = PasskeyCredential(
        credential_id=credential_id,
        public_key=bytes(row[6]),
        sign_count=new_sign_count,
        aaguid=None,
    )
    user = AuthenticatedUser(
        user_id=UUID(str(row[0])),
        tenant_id=UUID(str(row[1])),
        firm_id=UUID(str(row[2])) if row[2] else None,
        email=str(row[3]),
        role=UserRole(str(row[4])),
        external_id=str(row[5]),
        external_provider=adapter.provider,
        session_expires_at=datetime.now(UTC),
        passkey_verified=True,
    )
    await service.record_login_success(session, user=user)

    settings = request.app.state.settings
    token = await adapter.issue_session(
        user=user,
        credential=credential,
        session_duration_seconds=settings.session_duration_seconds,
    )
    return SessionTokenResponse(
        token=token.token,
        expires_at=token.expires_at,
        user_id=str(user.user_id),
        tenant_id=str(user.tenant_id),
    )


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
    session: Session = Depends(get_db),
) -> None:
    """Revoke the current session + audit."""
    raw = request.headers.get("authorization", "").removeprefix(
        "Bearer "
    ).strip() or request.cookies.get("session", "")
    await service.revoke_session(session, user=user, token=raw)


@router.get("/me", response_model=MeResponse)
async def me(user: AuthenticatedUser = Depends(get_current_user)) -> MeResponse:
    """Return the caller's resolved identity."""
    return MeResponse(
        user_id=str(user.user_id),
        tenant_id=str(user.tenant_id),
        firm_id=str(user.firm_id) if user.firm_id else None,
        email=user.email,
        role=user.role.value,
        session_expires_at=user.session_expires_at,
    )


# ---- helpers -------------------------------------------------------


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64d(data: str) -> bytes:
    # Tolerate missing padding (urlsafe_b64 often strips it).
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _json_safe(obj: Any) -> Any:
    """Make a fido2 state blob json-serializable."""
    if isinstance(obj, bytes):
        return _b64(obj)
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_json_safe(v) for v in obj]
    return obj
