"""Client portal auth routes (R26.4).

Flow:

1. Preparer/Firm_Administrator invites a Client — a separate route
   in P1.2 — which calls ``AuthService.issue_magic_link`` and
   triggers the email adapter. This file only handles what the
   Client sees.
2. Client clicks the email link → ``/portal/magic-link/consume``
   with the token. We mark it used, resolve the tenant+email, and
   redirect to passkey enrollment if the Client has no passkey yet.
3. On second + subsequent visits, the Client logs in via the
   standard ``/auth/login/*`` routes — the same passkey flow as
   Preparer users, gated on ``role = 'client_portal'``.

Magic-link issuance and consumption are audit-logged by the service
layer; these routes just translate HTTP into service calls.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from accounting_parser.api.deps import get_auth_service, get_db_unauthed
from accounting_parser.auth.service import AuthService, InvalidMagicLinkError

router = APIRouter()


class MagicLinkStartBody(BaseModel):
    tenant_id: str
    email: EmailStr


class MagicLinkConsumeBody(BaseModel):
    raw_token: str


class MagicLinkStartResponse(BaseModel):
    # We deliberately do not return the raw token to the client that
    # called start() — the raw token is delivered by email and is
    # only observable at issue time by the service + email sender.
    # This endpoint is internal-facing (called by the portal-invite
    # route in P1.2) but we keep the shape tight regardless.
    delivered: bool = True
    expires_at: str


class MagicLinkConsumeResponse(BaseModel):
    tenant_id: str
    email: str
    next_step: str  # "enroll_passkey" or "login"


@router.post("/magic-link/start", response_model=MagicLinkStartResponse)
async def magic_link_start(
    body: MagicLinkStartBody,
    service: AuthService = Depends(get_auth_service),
    session: Session = Depends(get_db_unauthed),
) -> MagicLinkStartResponse:
    """Issue a magic link.

    In a production flow this is called by an authenticated invite
    route that authorizes the inviter; at MVP the start endpoint is
    allow-listed (unauthenticated) to support the installer's
    "bootstrap a first client user" path. Downstream P1.2 tightens
    this when the invite UI ships.
    """
    issued = await service.issue_magic_link(
        session,
        tenant_id=UUID(body.tenant_id),
        email=body.email,
    )
    # Hand raw token off to the email sender here. P1.2 wires the
    # actual email adapter; for now we just stash the raw token in
    # server logs (structured, redacted) — NOT in the response.
    import structlog

    logger = structlog.get_logger(__name__)
    logger.info(
        "magic_link.issued",
        tenant_id=str(issued.tenant_id),
        email=issued.email,
        expires_at=issued.expires_at.isoformat(),
        # raw_token intentionally omitted from structured log too;
        # redaction middleware in P2.2 enforces this globally, but
        # we drop at the source as defense-in-depth.
    )
    return MagicLinkStartResponse(
        delivered=True,
        expires_at=issued.expires_at.isoformat(),
    )


@router.post("/magic-link/consume", response_model=MagicLinkConsumeResponse)
async def magic_link_consume(
    body: MagicLinkConsumeBody,
    service: AuthService = Depends(get_auth_service),
    session: Session = Depends(get_db_unauthed),
) -> MagicLinkConsumeResponse:
    """Verify a magic link and tell the client what to do next."""
    try:
        tenant_id, email = await service.consume_magic_link(session, raw_token=body.raw_token)
    except InvalidMagicLinkError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    # If the corresponding user has any webauthn_credential, next
    # step is standard login; otherwise enroll first. Query runs
    # under the newly-pinned tenant context.
    from sqlalchemy import text

    session.execute(
        text("SELECT set_config('app.tenant_id', :tid, false)"),
        {"tid": str(tenant_id)},
    )
    row = session.execute(
        text(
            """
            SELECT EXISTS(
              SELECT 1
              FROM app_user u
              JOIN webauthn_credential wc ON wc.user_id = u.id
              WHERE u.email = :email
            )
            """
        ),
        {"email": email},
    ).scalar_one()
    next_step = "login" if row else "enroll_passkey"

    return MagicLinkConsumeResponse(
        tenant_id=str(tenant_id),
        email=email,
        next_step=next_step,
    )
