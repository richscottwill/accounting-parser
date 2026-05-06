"""SQLAlchemy declarative Base.

Models are registered via their module being imported; ``Base.metadata``
is then used by Alembic autogenerate. The concrete model modules are
registered in ``accounting_parser.db.models`` so the Alembic env file
only needs to import ``Base`` to see every table.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for every ORM model in the project."""
