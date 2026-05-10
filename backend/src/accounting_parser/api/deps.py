"""FastAPI dependency-injection functions.

Every route that needs the authenticated user, a DB session, or an
auth-service instance imports from here. Kept in a single module so
the dependency graph is traceable without grep.

### Invariant: one Session per request

The ``get_db`` dependency opens a SQLAlchemy Session, sets the RLS
tenant context from the middleware-attached ``AuthenticatedUser``,
and closes it on response. No handler creates a Session directly.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, FastAPI, HTTPException, Request
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from accounting_parser.auth.adapter import AuthAdapter, AuthenticatedUser
from accounting_parser.auth.service import AuthService
from accounting_parser.db.session import set_tenant_context


def install_dependencies(app: FastAPI, *, engine: Engine, adapter: AuthAdapter) -> None:
    """Attach engine and adapter to app state.

    Called by ``create_app``. Kept as a function so tests can swap
    engines between test cases without rebuilding the whole FastAPI
    instance.
    """
    app.state.engine = engine
    app.state.auth_adapter = adapter
    app.state.session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    # Platform-admin engine: used only by signup (which creates the
    # tenant row; the tenant table's RLS policy restricts inserts to
    # the tenant referenced by current setting). If a separate
    # platform engine wasn't injected we fall back to the app engine,
    # which is safe in tests (pgserver's default pg_hba is trust-auth)
    # but NOT in production — production wires a distinct engine.
    app.state.platform_engine = getattr(app.state, "platform_engine", engine)
    app.state.platform_session_factory = sessionmaker(
        bind=app.state.platform_engine, expire_on_commit=False
    )


def get_adapter(request: Request) -> AuthAdapter:
    """Return the configured auth adapter."""
    return request.app.state.auth_adapter  # type: ignore[no-any-return]


def get_auth_service(
    adapter: AuthAdapter = Depends(get_adapter),
) -> AuthService:
    """Build an ``AuthService`` bound to the active adapter."""
    return AuthService(adapter=adapter)


def get_db_unauthed(request: Request) -> Iterator[Session]:
    """Open a Session without pinning a tenant context.

    For allow-listed routes (signup, magic-link start/consume) the
    middleware hasn't identified a user yet — we rely on the service
    layer to set context after it decides which tenant the operation
    scopes to. Routes that call this MUST NOT run tenant-scoped
    queries before the service pins the context.
    """
    factory: sessionmaker = request.app.state.session_factory
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_platform_db(request: Request) -> Iterator[Session]:
    """Open a Session as platform_admin for signup + administrative ops.

    The Firm_Administrator bootstrap flow (R25.1) creates rows in the
    ``tenant`` table whose RLS policy restricts writes to an already-
    matching tenant_id — a circular requirement on the first row. The
    parent schema's design resolves this by running the installer path
    as ``platform_admin`` (BYPASSRLS). This dependency surfaces that
    path.

    Use SPARINGLY: every route using this dependency is subject to
    extra audit scrutiny because it sidesteps RLS.
    """
    factory: sessionmaker = request.app.state.platform_session_factory
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_current_user(request: Request) -> AuthenticatedUser:
    """Return the middleware-resolved principal or 401.

    Routes that require authentication depend on this; it both
    narrows the type (User, not User | None) and encodes the 401
    shape in one place.
    """
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user  # type: ignore[no-any-return]


def get_db(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> Iterator[Session]:
    """Open a Session with the current user's tenant context pinned.

    ``set_tenant_context`` runs inside this dependency so every
    query issued through the yielded Session sees the correct RLS
    context. Commits on clean return, rolls back on exception.
    """
    factory: sessionmaker = request.app.state.session_factory
    session: Session = factory()
    try:
        set_tenant_context(session, user.tenant_id)
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
