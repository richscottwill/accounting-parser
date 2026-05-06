"""Database session management with tenant context.

Two critical invariants enforced here:

1. Application sessions connect as ``app_user``, which has ``NOBYPASSRLS``.
   At startup the app checks ``pg_roles`` and refuses to start if
   ``app_user`` has ``BYPASSRLS`` set.

2. Every transaction must set ``app.tenant_id`` on the session before
   running any tenant-scoped query. Row-Level Security policies use
   ``current_setting('app.tenant_id')::uuid`` to filter rows.

Use ``get_app_session(engine, tenant_id)`` as a context manager to get a
session with RLS configured, or ``set_tenant_context(session, tenant_id)``
if you already have a session.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
from uuid import UUID

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker


class RlsViolationError(RuntimeError):
    """Raised when the app tries to query without a tenant context set."""


def set_tenant_context(session: Session, tenant_id: UUID) -> None:
    """Pin the RLS tenant for this session.

    Must be called before any tenant-scoped query. The setting is
    transaction-local when ``SET LOCAL`` is used; here we use the
    session-level ``SET`` so it persists across the life of the session.
    """
    session.execute(
        text("SELECT set_config('app.tenant_id', :tid, false)"),
        {"tid": str(tenant_id)},
    )


def clear_tenant_context(session: Session) -> None:
    """Explicitly clear the tenant context. Tests use this to prove RLS blocks
    unfiltered access."""
    session.execute(text("SELECT set_config('app.tenant_id', '', false)"))


@contextmanager
def get_app_session(engine: Engine, tenant_id: UUID) -> Iterator[Session]:
    """Open a Session with RLS tenant context already set.

    Commits on clean exit, rolls back on exception, always closes.
    """
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    session = SessionLocal()
    try:
        set_tenant_context(session, tenant_id)
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def assert_app_user_has_no_bypass_rls(engine: Engine) -> None:
    """Startup check: the connection role must NOT have BYPASSRLS.

    A role with BYPASSRLS would see every tenant's data. In production the
    application role (``app_user``) is explicitly created with NOBYPASSRLS,
    but this check guards against drift (e.g., a DBA flipping the bit by
    hand, or a test misconfiguration).
    """
    with engine.connect() as conn:
        role = conn.execute(text("SELECT current_user")).scalar_one()
        row = conn.execute(
            text("SELECT rolbypassrls FROM pg_roles WHERE rolname = :r"),
            {"r": role},
        ).first()
        if row is None:
            raise RlsViolationError(
                f"Cannot find role {role!r} in pg_roles; cannot verify RLS safety"
            )
        if row[0] is True:
            raise RlsViolationError(
                f"Role {role!r} has BYPASSRLS enabled. Application must run as "
                "a NOBYPASSRLS role (typically 'app_user'). Refusing to start."
            )
