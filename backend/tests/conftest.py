"""Pytest conftest: Postgres backend (pgserver or Docker), apply migrations.

Fixtures:
    pg_server         — session-scoped backend (pgserver if available,
                        else passthrough to Docker Postgres via
                        ACCOUNTING_PARSER_TEST_DSN).
    pg_dsn            — session-scoped superuser DSN (postgres://...).
    migrated_engine   — session-scoped SQLAlchemy engine against a freshly
                        migrated database. Migrations run once per session.
    app_engine        — module-scoped engine that connects AS app_user
                        (NOBYPASSRLS). This is what production code uses.
    db_session        — function-scoped session; rolls back at teardown so
                        tests are isolated without running migrations each
                        time.

On DevSpaces we use a Docker Compose Postgres (see docker-compose.yml at
repo root) because pgserver has no Python 3.13 wheel. Set
ACCOUNTING_PARSER_TEST_DSN to override; otherwise the default
DSN is the compose-file superuser.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

try:
    import pgserver  # type: ignore[import-not-found]
    _HAS_PGSERVER = True
except ImportError:
    pgserver = None  # type: ignore[assignment]
    _HAS_PGSERVER = False


_DEFAULT_DOCKER_DSN = (
    "postgresql+psycopg://accounting_parser:dev_only_password"
    "@localhost:5432/accounting_parser_dev"
)


@pytest.fixture(scope="session")
def pg_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[object]:
    """Boot a Postgres server for the session.

    Uses pgserver if installed; otherwise yields a sentinel and relies on the
    Docker Compose Postgres running at localhost:5432.
    """
    if _HAS_PGSERVER:
        data_dir = tmp_path_factory.mktemp("pgdata")
        srv = pgserver.get_server(str(data_dir), cleanup_mode="stop")  # type: ignore[union-attr]
        try:
            yield srv
        finally:
            srv.cleanup()
    else:
        # Reset the Docker DB to a clean slate each session.
        dsn = os.environ.get("ACCOUNTING_PARSER_TEST_DSN", _DEFAULT_DOCKER_DSN)
        engine = create_engine(dsn, future=True, isolation_level="AUTOCOMMIT")
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
            # Wipe any non-default roles from prior runs; ignore errors if absent.
            for role in ("app_user", "platform_admin"):
                try:
                    conn.execute(text(f'DROP OWNED BY "{role}" CASCADE'))
                except Exception:
                    pass
                try:
                    conn.execute(text(f'DROP ROLE "{role}"'))
                except Exception:
                    pass
        engine.dispose()
        yield object()


@pytest.fixture(scope="session")
def pg_dsn(pg_server: object) -> str:
    """Superuser DSN. Used only for setup / migrations, never by app code."""
    if _HAS_PGSERVER:
        uri = pg_server.get_uri()  # type: ignore[attr-defined]
        return uri.replace("postgresql://", "postgresql+psycopg://", 1)
    return os.environ.get("ACCOUNTING_PARSER_TEST_DSN", _DEFAULT_DOCKER_DSN)


@pytest.fixture(scope="session")
def migrated_engine(pg_dsn: str, pg_server: object) -> Iterator[Engine]:
    """Run Alembic migrations against a fresh database, return engine."""
    repo_root = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    env["ACCOUNTING_PARSER_DB_URL"] = pg_dsn
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic upgrade failed:\nSTDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )

    engine = create_engine(pg_dsn, future=True)
    with engine.begin() as conn:
        conn.execute(text("ALTER ROLE app_user LOGIN PASSWORD 'test_only'"))
        conn.execute(text("ALTER ROLE platform_admin LOGIN PASSWORD 'test_only'"))
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def app_engine(migrated_engine: Engine, pg_dsn: str) -> Iterator[Engine]:
    """Engine that connects as ``app_user`` (NOBYPASSRLS)."""
    # Rewrite the userinfo portion of the DSN to app_user:test_only.
    # Works for both pgserver DSNs (postgres:@...) and Docker DSNs
    # (accounting_parser:dev_only_password@...).
    import re
    dsn = re.sub(
        r"(postgresql\+psycopg://)[^@]+@",
        r"\1app_user:test_only@",
        pg_dsn,
    )
    engine = create_engine(dsn, future=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def superuser_engine(migrated_engine: Engine) -> Engine:
    """Superuser engine for test setup operations that bypass RLS by design."""
    return migrated_engine


@pytest.fixture
def db_session(app_engine: Engine) -> Iterator[Session]:
    """App-user session with a rollback-only savepoint."""
    connection = app_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
