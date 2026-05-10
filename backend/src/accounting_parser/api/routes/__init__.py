"""HTTP route modules."""

from accounting_parser.api.routes.auth import router as auth_router
from accounting_parser.api.routes.client_portal import router as portal_router
from accounting_parser.api.routes.ingestion import router as ingestion_router

__all__ = ["auth_router", "ingestion_router", "portal_router"]
