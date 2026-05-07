"""FastAPI application entry point.

Composition root: configures auth app state (engines + RLS safety check),
mounts the auth router, and exposes liveness/version endpoints.

Task 6 will add the ingestion router; Task 17 the workflow router.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from accounting_parser import __version__
from accounting_parser.auth.routes import router as auth_router
from accounting_parser.auth.state import configure_auth_app_state
from accounting_parser.config import get_settings
from accounting_parser.ingestion.routes import router as ingestion_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """App-lifetime setup: wire engines and run startup RLS check."""
    configure_auth_app_state(app)
    yield
    # Dispose engines on shutdown.
    for attr in ("app_engine", "platform_engine"):
        engine = getattr(app.state, attr, None)
        if engine is not None:
            engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Accounting document parser for solo-practice CPAs",
        lifespan=lifespan,
    )

    # CORS: dev origin (Vite) only by default. Production overrides via env.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.webauthn_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_router)
    app.include_router(ingestion_router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
