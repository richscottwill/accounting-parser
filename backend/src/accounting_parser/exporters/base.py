"""TargetSystemAdapter Protocol + blocker infrastructure.

Every exporter follows the refuse-to-emit posture: ``validate(engagement)``
returns blockers; ``emit(engagement)`` refuses if any blocker exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from accounting_parser.model.canonical import WorkingTrialBalance


@dataclass(frozen=True)
class ExportBlocker:
    """A reason the export cannot proceed."""

    rule_id: str
    message: str
    severity: str = "blocker"  # always blocker; lower severities are warnings


@dataclass(frozen=True)
class ExportResult:
    target_system: str
    artifacts: tuple[Path, ...]
    blockers: tuple[ExportBlocker, ...]

    @property
    def emitted(self) -> bool:
        return not self.blockers and len(self.artifacts) > 0


class RefuseToEmit(Exception):  # noqa: N818
    """Raised when emit() is called with outstanding blockers."""


class TargetSystemAdapter(Protocol):
    target_system: str

    def validate(self, wtb: WorkingTrialBalance) -> list[ExportBlocker]:
        """Return 0 or more blockers; empty list means emit() will succeed."""
        ...

    def emit(self, wtb: WorkingTrialBalance, output_dir: Path) -> ExportResult:
        """Produce the vendor artifact(s). MUST refuse if validate() returns
        any blockers."""
        ...
