"""FastAPI application factory.

The factory pattern matters here because:

1. Tests need to construct isolated apps with injected adapters
   (mock Authentik, in-memory session factories). A module-level
   ``app = FastAPI()`` locks in the production wiring.
2. The compose stack needs the same factory so the uvicorn
   entry-point doesn't diverge from test setup.
3. A future multi-process deployment (if R30 ever lifts the single-
   box assumption) can call ``create_app()`` per worker.
"""

from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from accounting_parser import __version__
from accounting_parser.api.deps import install_dependencies
from accounting_parser.api.routes import auth_router, portal_router
from accounting_parser.auth.adapter import AuthAdapter
from accounting_parser.auth.authentik import AuthentikAuthAdapter, AuthentikConfig
from accounting_parser.auth.middleware import AuthMiddleware
from accounting_parser.config import Settings, get_settings


def create_app(
    *,
    settings: Settings | None = None,
    adapter: AuthAdapter | None = None,
    engine: Engine | None = None,
) -> FastAPI:
    """Build a configured FastAPI app.

    Arguments are optional for production (env-driven defaults) and
    supplied by tests (explicit injection). Explicit injection wins
    over defaults when both are present.
    """
    resolved_settings = settings or get_settings()
    resolved_adapter = adapter or _default_adapter(resolved_settings)
    resolved_engine = engine or create_engine(resolved_settings.db_url, future=True)

    app = FastAPI(
        title="accounting-parser",
        version=__version__,
        description=(
            "Accounting document parser for solo-practice CPAs " "(self-hosted single-firm fork)."
        ),
    )
    app.state.settings = resolved_settings
    app.state.auth_adapter = resolved_adapter
    app.state.engine = resolved_engine

    install_dependencies(app, engine=resolved_engine, adapter=resolved_adapter)

    app.add_middleware(AuthMiddleware, adapter=resolved_adapter)

    app.include_router(auth_router, prefix="/auth", tags=["auth"])
    app.include_router(portal_router, prefix="/portal", tags=["portal"])

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        """Liveness probe.

        R30.5 defines a richer self-hosted ``/health`` endpoint
        with service-health JSON; that lands in P3.4. This endpoint
        keeps the parent spec's lightweight liveness shape so
        compose healthchecks don't need to parse the richer payload.
        """
        return {"status": "ok", "version": __version__}

    return app


def _default_adapter(settings: Settings) -> AuthAdapter:
    """Construct the adapter named by ``settings.auth_adapter``."""
    if settings.auth_adapter == "authentik":
        config = AuthentikConfig(
            base_url=settings.authentik_base_url,
            client_id=settings.authentik_client_id,
            api_token=settings.authentik_api_token.get_secret_value(),
            jwks_url=settings.authentik_jwks_url,
            audience=settings.authentik_audience,
            issuer=settings.authentik_issuer,
            session_signing_key=settings.session_signing_key_pem.get_secret_value(),
            session_signing_kid=settings.session_signing_kid,
        )
        return AuthentikAuthAdapter(config)
    if settings.auth_adapter == "cognito":
        # Deliberately left unusable — see cognito.py docstring.
        from accounting_parser.auth.cognito import CognitoAuthAdapter

        return CognitoAuthAdapter()
    # 'memory' — used only in tests; construction happens in fixtures,
    # not in the factory default path.
    raise RuntimeError(
        f"AUTH_ADAPTER={settings.auth_adapter!r} requested but no default "
        "construction path exists. Tests must inject the adapter explicitly."
    )
