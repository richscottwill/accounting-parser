"""FastAPI authentication middleware.

Placed ahead of every route so that by the time a handler runs:

- ``request.state.user`` is an ``AuthenticatedUser`` or None.
- If a user is present, ``set_tenant_context`` has been called on
  the request-scoped DB session so RLS is active.
- Unauthenticated routes (``/healthz``, ``/auth/signup``,
  ``/auth/login``, ``/portal/magic-link/start``) are allow-listed;
  everything else requires a valid session or returns 401.

### Why a middleware rather than a dependency

Tenant pinning via ``SET`` runs at the DB session level; a
dependency resolves after FastAPI opens the DB session (via other
dependencies) which means the first query could be unpinned if the
order of dependency resolution drifts. A middleware runs before the
route and its dependencies, so we can set the tenant context on the
request-scoped session factory and any downstream DB dependency
inherits it.

### Concurrency property

50 concurrent requests across different tenants each get their own
request-scoped Session (FastAPI spawns one per dep resolution), and
each Session's ``app.tenant_id`` is set by this middleware before
the dependency chain runs. No tenant_id leak between requests. This
is exercised by the property test in
``tests/auth/test_concurrent_sessions.py``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from accounting_parser.auth.adapter import AuthAdapter, SessionVerificationError

_ALLOW_LIST_PREFIXES: tuple[str, ...] = (
    "/healthz",
    "/metrics",
    "/auth/signup",
    "/auth/login",
    "/auth/passkey/register/begin",  # initial registration challenge
    "/auth/passkey/register/complete",
    "/portal/magic-link/start",
    "/portal/magic-link/consume",
    "/openapi.json",
    "/docs",
    "/redoc",
)


class AuthMiddleware(BaseHTTPMiddleware):
    """Resolve session tokens and attach the principal to ``request.state``.

    Does NOT set the RLS tenant context — that happens inside the
    request-scoped DB session dependency (``api/deps.py``). The
    middleware's only responsibility is identifying the principal.
    This keeps the middleware synchronous-friendly and avoids
    opening a Session just to pin a context var we may not use.
    """

    def __init__(self, app: ASGIApp, adapter: AuthAdapter) -> None:
        super().__init__(app)
        self.adapter = adapter

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Attach None by default so downstream deps can check
        # ``request.state.user`` without a ``hasattr``.
        request.state.user = None

        if _is_allow_listed(request.url.path):
            return await call_next(request)

        raw_token = _extract_bearer(request)
        if raw_token is None:
            return _unauthorized("missing session token")

        try:
            user = await self.adapter.authenticate_request(raw_token)
        except SessionVerificationError:
            # Structural malformation — likely a bug or malicious
            # client. Log internally (via the structured logging
            # stack added in P2.2) and reject generically.
            return _unauthorized("invalid session token")

        if user is None:
            return _unauthorized("invalid or expired session")

        request.state.user = user
        return await call_next(request)


def _is_allow_listed(path: str) -> bool:
    """Return True if a request path is unauthenticated.

    Exact-prefix match is deliberate — ``/auth/signup`` matches
    ``/auth/signup`` and ``/auth/signup/`` but not anything else.
    """
    return any(path == prefix or path.startswith(prefix + "/") for prefix in _ALLOW_LIST_PREFIXES)


def _extract_bearer(request: Request) -> str | None:
    """Pull a Bearer token from the Authorization header or a cookie.

    We accept both so the SPA can use cookies (safer against JS
    exfiltration) and CLI / programmatic clients can use headers
    (simpler for curl testing).
    """
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:]
    cookie = request.cookies.get("session")
    if cookie:
        return cookie
    return None


def _unauthorized(reason: str) -> Response:
    """Construct a 401 response.

    Message is intentionally generic; the structured log carries
    the real reason. This prevents credential-oracle leakage.
    """
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=401,
        content={"detail": "Unauthorized"},
        headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
    )
