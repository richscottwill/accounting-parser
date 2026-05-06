"""Pytest conftest: boot pgserver once per session, apply migrations.

Fixtures:
    pg_server         — session-scoped pgserver instance.
    pg_dsn            — session-scoped DSN string (postgres://...).
    migrated_engine   — session-scoped SQLAlchemy engine against a freshly
                        migrated database. Migrations run once.
    app_engine        — module-scoped engine that connects AS app_user
                        (NOBYPASSRLS). This is what production code uses.
    db_session        — function-scoped session; rolls back at teardown so
                        tests are isolated without running migrations each
                        time.

The DB is created fresh each pytest session. pgserver owns the data dir
under tmp_path_factory so nothing leaks between runs.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pgserver  # type: ignore[import-not-found]
import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session


@pytest.fixture(scope="session")
def pg_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[object]:
    """Boot a Postgres server in a session-scoped tempdir."""
    data_dir = tmp_path_factory.mktemp("pgdata")
    srv = pgserver.get_server(str(data_dir), cleanup_mode="stop")
    try:
        yield srv
    finally:
        srv.cleanup()


@pytest.fixture(scope="session")
def pg_dsn(pg_server: object) -> str:
    """Superuser DSN. Used only for setup / migrations, never by app code."""
    uri = pg_server.get_uri()  # type: ignore[attr-defined]
    # pgserver returns postgresql://... which SQLAlchemy maps to psycopg2.
    # We use psycopg v3; force that dialect.
    return uri.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture(scope="session")
def migrated_engine(pg_dsn: str, pg_server: object) -> Iterator[Engine]:
    """Run Alembic migrations against a fresh database, return engine."""
    # Run alembic upgrade head against the superuser DSN. The migration
    # creates the app_user role; subsequent fixtures connect as app_user.
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

    # Set a password on app_user so we can log in as it. pgserver's default
    # trust-auth setup accepts any password, but SQLAlchemy needs something
    # in the DSN.
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
    dsn = pg_dsn.replace("postgres:@", "app_user:test_only@", 1)
    engine = create_engine(dsn, future=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def superuser_engine(migrated_engine: Engine) -> Engine:
    """Superuser engine (the default pgserver postgres role) for test setup
    operations like seeding tenants that bypass RLS by design."""
    return migrated_engine


@pytest.fixture
def db_session(app_engine: Engine) -> Iterator[Session]:
    """App-user session with a rollback-only savepoint.

    Tests get a clean slate without re-running migrations. The outer
    transaction is rolled back at teardown.
    """
    connection = app_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
