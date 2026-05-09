"""uvicorn entry-point.

This module imports the app factory and exposes a module-level ``app``
for uvicorn and friends. Production invocation:

    uvicorn accounting_parser.main:app --host 0.0.0.0 --port 8000

Tests use ``accounting_parser.api.create_app`` directly so they can
inject alternate adapters and engines.
"""

from __future__ import annotations

from accounting_parser.api import create_app

app = create_app()
