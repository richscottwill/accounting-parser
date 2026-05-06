"""Alembic environment configuration.

Resolves the database URL from ``ACCOUNTING_PARSER_DB_URL`` at runtime.
Model metadata comes from the ``Base`` class declared in
``accounting_parser.db.base``.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from accounting_parser.db.base import Base  # noqa: F401 — import for side effects

# --- Config ---------------------------------------------------------------

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

db_url = os.environ.get("ACCOUNTING_PARSER_DB_URL")
if not db_url:
    raise RuntimeError(
        "ACCOUNTING_PARSER_DB_URL environment variable must be set before "
        "running Alembic. For local dev with pgserver, the backend fixture "
        "sets this automatically; for direct invocation, export it first."
    )
config.set_main_option("sqlalchemy.url", db_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without connecting to the DB. Emits SQL to stdout."""
    context.configure(
        url=db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the DB and run migrations inside a transaction."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
