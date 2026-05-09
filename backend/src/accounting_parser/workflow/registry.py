"""Step registry.

A workflow template is a list of step references; the registry
resolves each reference to a concrete handler. Handlers are
Protocol-conforming callables keyed by ``step_type``.

### Built-in step types

Mirrors parent R10.3:

- ``parse``                      — run parsers over a Document set.
- ``classify``                   — apply classifier rules to parsed accounts.
- ``validate``                   — run validators; produce findings.
- ``require_preparer_review``    — pause until a Preparer approves.
- ``require_reviewer_signoff``   — pause until a Reviewer signs off.
- ``post_adjustments``           — apply approved AJEs to the WTB.
- ``emit_export``                — produce a Target_System_Export.

At P1.4 the registry ships stub handlers for the compute steps
(parse / classify / validate / post_adjustments / emit_export) that
record that they ran and produce empty outputs. Real implementations
live in the existing parent-shipped packages (parser/, classifier/,
validator/, etc.) — wiring them in is a downstream task, P1.4 only
proves the orchestration contract.

Pause steps (require_preparer_review / require_reviewer_signoff)
are first-class — their handlers produce a pause signal that the
runner converts into ``WorkflowState.PAUSED_AWAITING_INPUT``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol
from uuid import UUID


class BuiltinStepType(str, Enum):
    PARSE = "parse"
    CLASSIFY = "classify"
    VALIDATE = "validate"
    REQUIRE_PREPARER_REVIEW = "require_preparer_review"
    REQUIRE_REVIEWER_SIGNOFF = "require_reviewer_signoff"
    POST_ADJUSTMENTS = "post_adjustments"
    EMIT_EXPORT = "emit_export"


class StepStatus(str, Enum):
    """What a handler returns to the runner."""

    COMPLETED = "completed"
    PAUSED = "paused"
    FAILED = "failed"


@dataclass(frozen=True)
class StepContext:
    """Read-only context the runner passes to each handler.

    Contains the ids the handler needs to do its work plus the
    run-scoped blackboard so later steps can read earlier outputs.
    """

    tenant_id: UUID
    engagement_id: UUID
    run_id: UUID
    step_name: str
    step_type: str
    step_config: dict[str, Any]
    run_context: dict[str, Any]


@dataclass
class StepResult:
    """What a handler returns."""

    status: StepStatus
    # Merged into the run context under the step's name.
    output: dict[str, Any] = field(default_factory=dict)
    # Populated when status == PAUSED. Shape:
    #   {"required_role": "preparer" | "reviewer", "reason": "..."}
    pause_reason: dict[str, Any] = field(default_factory=dict)
    # Populated when status == FAILED.
    error: str | None = None


class StepHandler(Protocol):
    """Callable the runner invokes per step."""

    def __call__(self, ctx: StepContext) -> StepResult: ...


class StepRegistry:
    """Lookup table step_type → handler.

    Constructed fresh per process. The API layer registers default
    handlers at startup; tests register stubs.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, StepHandler] = {}

    def register(self, step_type: str, handler: StepHandler) -> None:
        """Register a handler for a step type. Replaces any existing."""
        self._handlers[step_type] = handler

    def get(self, step_type: str) -> StepHandler:
        try:
            return self._handlers[step_type]
        except KeyError as e:
            raise KeyError(
                f"no handler registered for step_type {step_type!r}; "
                f"known types: {sorted(self._handlers)}"
            ) from e

    def register_builtin_stubs(self) -> None:
        """Register no-op handlers for every built-in step type.

        P1.4 deliverable: the orchestration works end-to-end with
        stub compute steps. Real handlers land as subsequent work
        (parent Task 7/13 classifier + validator are already shipped;
        wiring them in is P1.4-followup, not P1.4 itself).
        """
        for step_type in BuiltinStepType:
            if step_type is BuiltinStepType.REQUIRE_PREPARER_REVIEW:
                self.register(step_type.value, _pause_step("preparer"))
            elif step_type is BuiltinStepType.REQUIRE_REVIEWER_SIGNOFF:
                self.register(step_type.value, _pause_step("reviewer"))
            else:
                self.register(step_type.value, _noop_compute_step(step_type.value))


# ---- Built-in handler factories ---------------------------------


def _noop_compute_step(step_type: str) -> StepHandler:
    """Return a handler that records the step ran and emits no output."""

    def _handler(ctx: StepContext) -> StepResult:
        return StepResult(
            status=StepStatus.COMPLETED,
            output={"step_type": step_type, "stub": True},
        )

    return _handler


def _pause_step(required_role: str) -> StepHandler:
    """Return a handler that always pauses, requiring the given role."""

    def _handler(ctx: StepContext) -> StepResult:
        return StepResult(
            status=StepStatus.PAUSED,
            pause_reason={
                "required_role": required_role,
                "reason": ctx.step_config.get("reason", f"awaiting {required_role} input"),
                "step_name": ctx.step_name,
            },
        )

    return _handler
