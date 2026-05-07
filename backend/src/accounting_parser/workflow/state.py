"""Workflow state machine — pure data + transition rules.

State enums and the allowed-transition matrix. Engine code reads this
module to decide whether a proposed transition is legal.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class RunState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED_AWAITING_INPUT = "paused_awaiting_input"
    COMPLETED = "completed"
    FAILED = "failed"


class StepState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED_AWAITING_INPUT = "paused_awaiting_input"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


# Allowed state transitions — engine refuses anything not listed.
_RUN_TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.PENDING: {RunState.RUNNING, RunState.FAILED},
    RunState.RUNNING: {RunState.PAUSED_AWAITING_INPUT, RunState.COMPLETED, RunState.FAILED},
    RunState.PAUSED_AWAITING_INPUT: {RunState.RUNNING, RunState.FAILED},
    RunState.COMPLETED: set(),
    RunState.FAILED: set(),
}

_STEP_TRANSITIONS: dict[StepState, set[StepState]] = {
    StepState.PENDING: {StepState.RUNNING, StepState.SKIPPED},
    StepState.RUNNING: {
        StepState.PAUSED_AWAITING_INPUT, StepState.SUCCEEDED, StepState.FAILED
    },
    StepState.PAUSED_AWAITING_INPUT: {StepState.RUNNING, StepState.SUCCEEDED, StepState.FAILED},
    StepState.SUCCEEDED: set(),
    StepState.FAILED: set(),
    StepState.SKIPPED: set(),
}


def can_transition_run(from_: RunState, to: RunState) -> bool:
    return to in _RUN_TRANSITIONS.get(from_, set())


def can_transition_step(from_: StepState, to: StepState) -> bool:
    return to in _STEP_TRANSITIONS.get(from_, set())


class InvalidTransition(Exception):
    """Raised when a proposed state transition is not allowed."""


@dataclass
class StepOutcome:
    """Return shape of a step executor."""

    state: StepState
    output: dict[str, Any]
    # When set, the run pauses at this step until the matching review/signoff
    # event arrives. The engine transitions run → paused_awaiting_input.
    pause_reason: str | None = None
