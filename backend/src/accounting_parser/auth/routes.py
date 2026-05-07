"""FastAPI routes for auth: signup, login, me.

URL layout:

- ``POST /auth/signup/begin``          — Phase 1 of signup
- ``POST /auth/signup/complete``       — Phase 2 of signup
- ``POST /auth/login/begin``           — Start login (email lookup)
- ``POST /auth/login/complete``        — Complete login with assertion
- ``GET  /auth/me``                    — Current-user introspection
- ``POST /auth/webauthn/register/begin`` — Add an additional passkey
- ``POST /auth/webauthn/register/complete``

All request/response shapes are Pydantic v2 models so OpenAPI docs are
automatic and payload validation is strict.
"""
from __future__ import annotations

import base64
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from accounting_parser.auth.middleware import (
    get_anonymous_db_session,
    get_current_claims,
    get_db_session,
)
from accounting_parser.auth.service import (
    begin_login,
    begin_signup,
    complete_login,
    complete_signup,
)
from accounting_parser.auth.session import SessionClaims
from accounting_parser.auth.webauthn import (
    begin_registration,
    complete_registration,
)

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------

class SignupBeginRequest(BaseModel):
    firm_name: str = Field(min_length=2, max_length=200)
    admin_email: EmailStr
    admin_ptin: str | None = Field(default=None, pattern=r"^P\d{8}$")


class SignupBeginResponse(BaseModel):
    tenant_id: UUID
    firm_id: UUID
    user_id: UUID
    registration_options: dict[str, Any]
    signup_token: str


class SignupCompleteRequest(BaseModel):
    signup_token: str
    client_data_json_b64: str
    attestation_object_b64: str


class SignupCompleteResponse(BaseModel):
    tenant_id: UUID
    firm_id: UUID
    user_id: UUID
    session_token: str


class LoginBeginRequest(BaseModel):
    email: EmailStr


class LoginBeginResponse(BaseModel):
    assertion_options: dict[str, Any]
    login_token: str


class LoginCompleteRequest(BaseModel):
    login_token: str
    credential_id_b64: str
    client_data_json_b64: str
    authenticator_data_b64: str
    signature_b64: str


class LoginCompleteResponse(BaseModel):
    session_token: str


class MeResponse(BaseModel):
    user_id: UUID
    tenant_id: UUID
    firm_id: UUID | None
    role: str
    email: EmailStr


class WebAuthnRegisterBeginResponse(BaseModel):
    options: dict[str, Any]
    challenge_id: UUID


class WebAuthnRegisterCompleteRequest(BaseModel):
    challenge_id: UUID
    client_data_json_b64: str
    attestation_object_b64: str
    friendly_name: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_platform_session_dep(request: Request):
    """Open a session on the platform_admin engine for signup bootstrap."""
    engine = request.app.state.platform_engine
    from sqlalchemy.orm import sessionmaker

    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _b64d(s: str) -> bytes:
    """Base64url (or standard base64) decode, tolerating either scheme."""
    # fido2 server expects raw bytes; browsers send base64url, Playwright
    # virtual authenticator emits standard base64. Accept both.
    s = s.strip()
    s_std = s.replace("-", "+").replace("_", "/")
    padding = "=" * (-len(s_std) % 4)
    return base64.b64decode(s_std + padding)


# ---------------------------------------------------------------------------
# Signup
# ---------------------------------------------------------------------------

@router.post("/signup/begin", response_model=SignupBeginResponse)
def signup_begin(
    req: SignupBeginRequest,
    session: Annotated[Session, Depends(_get_platform_session_dep)],
) -> SignupBeginResponse:
    """Phase 1: create tenant+firm+admin, return passkey registration options."""
    try:
        result = begin_signup(
            session,
            firm_name=req.firm_name,
            admin_email=req.admin_email,
            admin_ptin=req.admin_ptin,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"reason_code": "signup_failed", "message": str(e)},
        ) from e
    return SignupBeginResponse(
        tenant_id=result.tenant_id,
        firm_id=result.firm_id,
        user_id=result.user_id,
        registration_options=result.registration_options,
        signup_token=result.signup_token,
    )


@router.post("/signup/complete", response_model=SignupCompleteResponse)
def signup_complete(
    req: SignupCompleteRequest,
    session: Annotated[Session, Depends(_get_platform_session_dep)],
) -> SignupCompleteResponse:
    """Phase 2: verify passkey attestation, issue session JWT."""
    try:
        result = complete_signup(
            session,
            signup_token=req.signup_token,
            client_data_json=_b64d(req.client_data_json_b64),
            attestation_object=_b64d(req.attestation_object_b64),
        )
    except Exception as e:
        import logging

        logging.getLogger(__name__).exception("signup/complete failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "reason_code": "signup_complete_failed",
                "message": str(e),
                "exception_type": type(e).__name__,
            },
        ) from e
    return SignupCompleteResponse(
        tenant_id=result.tenant_id,
        firm_id=result.firm_id,
        user_id=result.user_id,
        session_token=result.session_token,
    )


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@router.post("/login/begin", response_model=LoginBeginResponse)
def login_begin(
    req: LoginBeginRequest,
    session: Annotated[Session, Depends(_get_platform_session_dep)],
) -> LoginBeginResponse:
    try:
        result = begin_login(session, email=req.email)
    except ValueError as e:
        # Constant-time-ish: same error shape for unknown-email and no-creds.
        # Real rate limiting lives in the ingress/WAF tier; this is app-layer.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"reason_code": "login_begin_failed"},
        ) from e
    return LoginBeginResponse(
        assertion_options=result.assertion_options,
        login_token=result.login_token,
    )


@router.post("/login/complete", response_model=LoginCompleteResponse)
def login_complete(
    req: LoginCompleteRequest,
    session: Annotated[Session, Depends(_get_platform_session_dep)],
) -> LoginCompleteResponse:
    try:
        result = complete_login(
            session,
            login_token=req.login_token,
            credential_id_bytes=_b64d(req.credential_id_b64),
            client_data_json=_b64d(req.client_data_json_b64),
            authenticator_data=_b64d(req.authenticator_data_b64),
            signature=_b64d(req.signature_b64),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"reason_code": "login_complete_failed", "message": str(e)},
        ) from e
    return LoginCompleteResponse(session_token=result.session_token)


# ---------------------------------------------------------------------------
# Me + additional passkey registration (authenticated)
# ---------------------------------------------------------------------------

@router.get("/me", response_model=MeResponse)
def me(
    claims: Annotated[SessionClaims, Depends(get_current_claims)],
) -> MeResponse:
    return MeResponse(
        user_id=claims.user_id,
        tenant_id=claims.tenant_id,
        firm_id=claims.firm_id,
        role=claims.role,
        email=claims.email,
    )


@router.post(
    "/webauthn/register/begin", response_model=WebAuthnRegisterBeginResponse
)
def webauthn_register_begin(
    claims: Annotated[SessionClaims, Depends(get_current_claims)],
    session: Annotated[Session, Depends(get_db_session)],
) -> WebAuthnRegisterBeginResponse:
    result = begin_registration(
        session,
        tenant_id=claims.tenant_id,
        user_id=claims.user_id,
        user_email=claims.email,
        display_name=claims.email,
    )
    return WebAuthnRegisterBeginResponse(
        options=result.options, challenge_id=result.challenge_id
    )


@router.post("/webauthn/register/complete")
def webauthn_register_complete(
    req: WebAuthnRegisterCompleteRequest,
    claims: Annotated[SessionClaims, Depends(get_current_claims)],
    session: Annotated[Session, Depends(get_db_session)],
) -> dict[str, str]:
    try:
        complete_registration(
            session,
            challenge_id=req.challenge_id,
            client_data_json=_b64d(req.client_data_json_b64),
            attestation_object=_b64d(req.attestation_object_b64),
            friendly_name=req.friendly_name,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"reason_code": "webauthn_register_failed", "message": str(e)},
        ) from e
    return {"status": "registered"}
