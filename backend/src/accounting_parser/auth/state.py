"""App-lifespan state: two engines and assorted startup checks.

The auth subsystem uses two Postgres connection pools:

- ``app_engine``: connects as ``app_user`` (NOBYPASSRLS). Used by every
  tenant-scoped request. RLS policies enforce tenant isolation.

- ``platform_engine``: connects as ``platform_admin`` (BYPASSRLS). Used
  exclusively by the signup bootstrap route, which creates tenant rows
  that no app_user session has the tenant context to insert. Every
  platform_engine use goes through the chained audit_log_entry so
  platform-level actions are tamper-evident.

``configure_auth_app_state(app)`` wires the engines + runs the startup
RLS-safety check defined in db/session.py.
"""
from __future__ import annotations

import re

from fastapi import FastAPI
from sqlalchemy import Engine, create_engine

from accounting_parser.config import Settings, get_settings
from accounting_parser.db.session import assert_app_user_has_no_bypass_rls


def _rewrite_user(dsn: str, user: str, password: str) -> str:
    """Replace the userinfo portion of a postgresql+psycopg DSN."""
    return re.sub(
        r"(postgresql\+psycopg://)[^@]+@",
        f"\\1{user}:{password}@",
        dsn,
    )


def build_app_engine(settings: Settings) -> Engine:
    dsn = _rewrite_user(settings.db_url, settings.db_app_user, settings.db_app_password)
    return create_engine(dsn, future=True, pool_pre_ping=True)


def build_platform_engine(settings: Settings) -> Engine:
    # platform_admin DSN: keep whatever the superuser credentials are.
    return create_engine(settings.db_url, future=True, pool_pre_ping=True)


def configure_auth_app_state(app: FastAPI, *, settings: Settings | None = None) -> None:
    """Wire engines into app.state and run startup RLS safety check.

    Idempotent — calling twice is safe.
    """
    settings = settings or get_settings()
    if getattr(app.state, "_auth_state_configured", False):
        return

    app.state.settings = settings
    app.state.app_engine = build_app_engine(settings)
    app.state.platform_engine = build_platform_engine(settings)

    # Startup RLS check. Refuses to start if app_user has BYPASSRLS.
    assert_app_user_has_no_bypass_rls(app.state.app_engine)

    app.state._auth_state_configured = True
