"""Schema-version migration pipeline.

When a canonical model's schema changes incompatibly, bump
``CURRENT_SCHEMA_VERSION`` in ``canonical.py`` and add a function here:

    def migrate_v1_to_v2(record: dict) -> dict:
        # rename field, split nested, etc.
        return record

Then register it in ``_MIGRATIONS``. ``migrate_to_current`` walks the chain.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from accounting_parser.model.pretty_printer import CURRENT_SCHEMA_VERSION


Migration = Callable[[dict[str, Any]], dict[str, Any]]

# Currently empty — schema_version 1 is the first. Add entries as schemas evolve.
_MIGRATIONS: dict[int, Migration] = {}


def migrate_to_current(record: dict[str, Any]) -> dict[str, Any]:
    """Walk a record from its stored schema_version up to the current one."""
    version = record.get("schema_version", 1)
    while version < CURRENT_SCHEMA_VERSION:
        fn = _MIGRATIONS.get(version)
        if fn is None:
            raise RuntimeError(
                f"No migration function registered for schema_version "
                f"{version} -> {version + 1}"
            )
        record = fn(record)
        version += 1
        record["schema_version"] = version
    return record
