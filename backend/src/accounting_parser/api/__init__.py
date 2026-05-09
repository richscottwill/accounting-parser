"""HTTP surface — FastAPI app factory and route registration.

Exposed:
- ``create_app`` — factory returning a FastAPI instance. Used by
  uvicorn entry-point and by tests that want a fresh app per test.
- ``deps`` — dependency injection functions (DB session, current
  user, auth adapter).
"""

from accounting_parser.api.app import create_app

__all__ = ["create_app"]
