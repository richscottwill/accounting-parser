"""Validator finding records."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCKER = "blocker"


class Finding(BaseModel):
    """One validator finding."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str
    severity: Severity
    message: str
    expected: str | None = None
    observed: str | None = None
    tolerance: Decimal | None = None
    source_reference: dict[str, Any] | None = None
