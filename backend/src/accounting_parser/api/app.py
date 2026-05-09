"""FastAPI application factory.

The factory pattern matters here because:

1. Tests need to construct isolated apps with injected adapters
   (mock Authentik, in-memory storage, mock scanners). A module-level
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
from accounting_parser.api.routes import auth_router, ingestion_router, portal_router
from accounting_parser.api.routes.workflows import router as workflows_router
from accounting_parser.auth.adapter import AuthAdapter
from accounting_parser.auth.authentik import AuthentikAuthAdapter, AuthentikConfig
from accounting_parser.auth.middleware import AuthMiddleware
from accounting_parser.config import Settings, get_settings
from accounting_parser.ingestion.virus_scan import ClamdVirusScanner, NullVirusScanner, VirusScanner
from accounting_parser.storage.adapter import DocumentStoreAdapter
from accounting_parser.storage.memory import InMemoryDocumentStoreAdapter
from accounting_parser.storage.minio import MinIODocumentStoreAdapter
from accounting_parser.workflow.registry import StepRegistry


def create_app(
    *,
    settings: Settings | None = None,
    adapter: AuthAdapter | None = None,
    engine: Engine | None = None,
    document_store: DocumentStoreAdapter | None = None,
    virus_scanner: VirusScanner | None = None,
    workflow_registry: StepRegistry | None = None,
) -> FastAPI:
    """Build a configured FastAPI app."""
    resolved_settings = settings or get_settings()
    resolved_adapter = adapter or _default_auth_adapter(resolved_settings)
    resolved_engine = engine or create_engine(resolved_settings.db_url, future=True)
    resolved_store = document_store or _default_document_store(resolved_settings)
    resolved_scanner = virus_scanner or _default_virus_scanner(resolved_settings)
    resolved_registry = workflow_registry or _default_workflow_registry()

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
    app.state.document_store = resolved_store
    app.state.virus_scanner = resolved_scanner
    app.state.workflow_registry = resolved_registry

    install_dependencies(app, engine=resolved_engine, adapter=resolved_adapter)

    app.add_middleware(AuthMiddleware, adapter=resolved_adapter)

    app.include_router(auth_router, prefix="/auth", tags=["auth"])
    app.include_router(portal_router, prefix="/portal", tags=["portal"])
    app.include_router(ingestion_router, tags=["documents"])
    app.include_router(workflows_router, tags=["workflows"])

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        """Liveness probe.

        R30.5 defines a richer self-hosted ``/health`` endpoint with
        service-health JSON; that lands in P3.4. This endpoint keeps
        the parent spec's lightweight liveness shape so compose
        healthchecks don't need to parse the richer payload.
        """
        return {"status": "ok", "version": __version__}

    return app


def _default_auth_adapter(settings: Settings) -> AuthAdapter:
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
        from accounting_parser.auth.cognito import CognitoAuthAdapter

        return CognitoAuthAdapter()
    raise RuntimeError(
        f"AUTH_ADAPTER={settings.auth_adapter!r} requested but no default "
        "construction path exists. Tests must inject the adapter explicitly."
    )


def _default_document_store(settings: Settings) -> DocumentStoreAdapter:
    if settings.doc_store_adapter == "minio":
        return MinIODocumentStoreAdapter(
            endpoint_url=settings.minio_endpoint_url,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key.get_secret_value(),
            region=settings.minio_region,
        )
    if settings.doc_store_adapter == "s3":
        from accounting_parser.storage.s3 import S3DocumentStoreAdapter

        return S3DocumentStoreAdapter(bucket=settings.storage_bucket)
    if settings.doc_store_adapter == "memory":
        return InMemoryDocumentStoreAdapter()
    raise RuntimeError(
        f"DOC_STORE_ADAPTER={settings.doc_store_adapter!r} requested "
        "but no default construction path exists. Tests inject directly."
    )


def _default_virus_scanner(settings: Settings) -> VirusScanner:
    if settings.virus_scanner == "null":
        return NullVirusScanner()
    if settings.virus_scanner == "clamd":
        return ClamdVirusScanner(host=settings.clamd_host, port=settings.clamd_port)
    raise RuntimeError(f"VIRUS_SCANNER={settings.virus_scanner!r} not recognized")


def _default_workflow_registry() -> StepRegistry:
    """Build a StepRegistry with built-in stub handlers.

    P1.4 ships stubs for compute steps (parse / classify / validate /
    post_adjustments / emit_export). Real handlers wire in once the
    SPA (P1.5) can drive end-to-end validation.
    """
    registry = StepRegistry()
    registry.register_builtin_stubs()
    return registry
