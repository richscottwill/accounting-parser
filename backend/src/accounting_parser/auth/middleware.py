"""FastAPI dependencies + middleware for authenticated requests.

Design:

- ``get_db_session`` is the FastAPI dependency every tenant-scoped route uses.
  It opens a SQLAlchemy session against the app_engine (NOBYPASSRLS role),
  extracts the Bearer token, decodes the session JWT, sets
  ``app.tenant_id`` on the session via ``set_tenant_context``, and yields
  the session. On exit, commits on success or rolls back on exception.

- ``require_role`` is a dependency factory producing a dependency that
  401/403s requests whose session role is not in the allowed set. Roles
  are hierarchical in practice (firm_administrator ⊇ preparer), but we
  enforce explicit role lists at each route rather than a lattice — easier
  to audit.

- ``get_current_user`` returns the decoded SessionClaims for use in
  handlers that need user identity beyond what the DB session carries.

This middleware is the HTTP/app-layer half of the tenant-isolation
guarantee. Postgres RLS (Task 3) is the data-layer half. Both must hold.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from accounting_parser.auth.session import SessionClaims, decode_session_token
from accounting_parser.db.session import set_tenant_context

logger = logging.getLogger(__name__)


def _get_app_engine(request: Request) -> Engine:
    """Retrieve the app-scoped engine from app.state."""
    engine: Engine | None = getattr(request.app.state, "app_engine", None)
    if engine is None:
        raise RuntimeError(
            "app.state.app_engine is not set. Configure at startup via "
            "configure_auth_app_state()."
        )
    return engine


def get_current_claims(
    authorization: Annotated[str | None, Header()] = None,
) -> SessionClaims:
    """Parse the Bearer token and return the SessionClaims.

    Raises 401 on any auth failure. Does NOT open a DB session.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"reason_code": "missing_authorization"},
        )
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"reason_code": "malformed_authorization"},
        )
    try:
        return decode_session_token(parts[1])
    except ValueError as e:
        logger.warning("Rejected session token", extra={"error": str(e)})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"reason_code": "invalid_token"},
        ) from e


def get_db_session(
    request: Request,
    claims: Annotated[SessionClaims, Depends(get_current_claims)],
) -> Iterator[Session]:
    """Open a Session with the tenant context already pinned.

    Commits on clean exit, rolls back on exception, always closes.
    """
    engine = _get_app_engine(request)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    session = SessionLocal()
    try:
        set_tenant_context(session, claims.tenant_id)
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_anonymous_db_session(request: Request) -> Iterator[Session]:
    """Open a Session for routes that run BEFORE authentication (signup, etc).

    No tenant context is set — only routes that explicitly handle the
    tenant-null case (e.g., signup bootstrap challenge) should use this.
    """
    engine = _get_app_engine(request)
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


def require_role(*allowed: str):
    """Dependency factory: 403 unless the caller's role is in ``allowed``."""

    def dep(
        claims: Annotated[SessionClaims, Depends(get_current_claims)],
    ) -> SessionClaims:
        if claims.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "reason_code": "role_not_authorized",
                    "required": list(allowed),
                    "role": claims.role,
                },
            )
        return claims

    return dep


def tenant_id_path_matches_claims(
    path_tenant_id: str,
    claims: SessionClaims,
) -> None:
    """Defensive check: the URL tenant_id must equal the token's tenant_id.

    This is layer 3 of tenant isolation (RLS + ORM filter + API dispatcher
    per design §6.3). Raise 403 on mismatch.
    """
    if str(claims.tenant_id) != path_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "reason_code": "tenant_path_mismatch",
                "path_tenant_id": path_tenant_id,
            },
        )
