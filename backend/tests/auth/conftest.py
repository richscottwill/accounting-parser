"""Auth test fixtures.

Builds on the top-level ``conftest.py`` pgserver fixtures. Adds:

- ``memory_adapter``  — a fresh ``MemoryAuthAdapter`` per test.
- ``auth_settings``   — ``Settings`` pointing at the test signing key.
- ``auth_service``    — ``AuthService`` wired to ``memory_adapter``.
- ``auth_app``        — FastAPI app constructed with injected adapter +
  engine + settings. One per test.
- ``auth_client``     — starlette ``TestClient`` wrapping ``auth_app``.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.engine import Engine

from accounting_parser.api import create_app
from accounting_parser.auth.memory import (
    MemoryAuthAdapter,
    audience_for_tests,
    issuer_for_tests,
    kid_for_tests,
    signing_key_pem_for_tests,
)
from accounting_parser.auth.service import AuthService
from accounting_parser.config import Settings


@pytest.fixture
def memory_adapter() -> MemoryAuthAdapter:
    return MemoryAuthAdapter()


@pytest.fixture
def auth_settings() -> Settings:
    """Settings tuned for tests (deterministic signing key, short TTLs)."""
    return Settings(
        db_url="postgresql+psycopg://unused-in-tests/unused",
        auth_adapter="authentik",
        authentik_base_url="http://authentik.test",
        authentik_client_id="test-client",
        authentik_api_token=SecretStr("test-token"),
        authentik_jwks_url="http://authentik.test/jwks",
        authentik_audience=audience_for_tests(),
        authentik_issuer=issuer_for_tests(),
        session_signing_key_pem=SecretStr(signing_key_pem_for_tests()),
        session_signing_kid=kid_for_tests(),
        session_duration_seconds=3600,
        magic_link_ttl_seconds=60,
        firm_rp_name="accounting-parser-test",
        firm_rp_id="localhost",
    )


@pytest.fixture
def auth_service(memory_adapter: MemoryAuthAdapter) -> AuthService:
    return AuthService(adapter=memory_adapter)


@pytest.fixture
def auth_app(
    memory_adapter: MemoryAuthAdapter,
    auth_settings: Settings,
    app_engine: Engine,
    superuser_engine: Engine,
):
    """FastAPI app with memory adapter + real migrated DB engine.

    ``superuser_engine`` is wired as the platform_engine so the signup
    route can create tenant + firm rows under BYPASSRLS. Regular
    request paths still use ``app_engine`` (NOBYPASSRLS).
    """
    app = create_app(
        settings=auth_settings,
        adapter=memory_adapter,
        engine=app_engine,
    )
    # Override the default (which was engine=app_engine) with the
    # real platform engine for signup.
    from sqlalchemy.orm import sessionmaker

    app.state.platform_engine = superuser_engine
    app.state.platform_session_factory = sessionmaker(bind=superuser_engine, expire_on_commit=False)
    return app


@pytest.fixture
def auth_client(auth_app) -> Iterator[TestClient]:
    with TestClient(auth_app) as client:
        yield client
