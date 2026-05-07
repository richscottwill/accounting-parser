"""Step-type registry — maps step_name string → executor callable.

Step executors are pure functions with the signature::

    def executor(ctx: StepContext) -> StepOutcome: ...

Where ``StepContext`` carries the session, tenant_id, engagement_id, run_id,
step config, and prior-step outputs. Registering a new step type is a
single ``@register_step("name")`` decorator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import UUID

from sqlalchemy.orm import Session

from accounting_parser.workflow.state import StepOutcome

StepExecutor = Callable[["StepContext"], StepOutcome]


@dataclass
class StepContext:
    session: Session
    tenant_id: UUID
    engagement_id: UUID
    workflow_run_id: UUID
    step_name: str
    step_config: dict[str, Any]
    previous_outputs: dict[str, Any] = field(default_factory=dict)


_REGISTRY: dict[str, StepExecutor] = {}


def register_step(name: str) -> Callable[[StepExecutor], StepExecutor]:
    """Decorator that registers an executor under a step-type name."""

    def _wrap(fn: StepExecutor) -> StepExecutor:
        if name in _REGISTRY:
            raise ValueError(f"Step type {name!r} is already registered")
        _REGISTRY[name] = fn
        return fn

    return _wrap


def get_step(name: str) -> StepExecutor:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown step type {name!r}")
    return _REGISTRY[name]


def known_step_types() -> list[str]:
    return sorted(_REGISTRY.keys())
