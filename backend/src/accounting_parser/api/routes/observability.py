"""Observability HTTP routes.

- ``GET /metrics`` — Prometheus scrape endpoint. Allow-listed in
  the auth middleware; accessed by the in-stack Prometheus scraper,
  not by users. In production the Caddy config restricts this to
  the compose network so external callers never hit it.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

router = APIRouter()


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    """Expose the Prometheus metrics body."""
    adapter = request.app.state.metrics_adapter
    if not hasattr(adapter, "expose_metrics"):
        # NullMetricsAdapter in tests: return an empty body. Tests
        # that assert metric contents use the adapter directly; this
        # endpoint is a prod-side contract.
        return Response(content=b"", media_type="text/plain; version=0.0.4")
    body = adapter.expose_metrics()
    return Response(content=body, media_type="text/plain; version=0.0.4")
