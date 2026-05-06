"""Scaffolding smoke test. Verifies the package imports and the app boots.

Real tests arrive with Tasks 3+.
"""

from fastapi.testclient import TestClient

from accounting_parser import __version__
from accounting_parser.main import app


def test_version_exposed() -> None:
    """Package version is readable."""
    assert __version__ == "0.1.0"


def test_healthz_endpoint() -> None:
    """Health endpoint returns 200 and reports the package version."""
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
