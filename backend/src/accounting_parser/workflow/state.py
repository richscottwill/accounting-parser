"""Workflow execution state model + DB row shapes.

Persistent tables live in migration 0004. In-memory dataclasses
here mirror those rows 1:1 so callers never touch the DB directly —
the runner serializes state transitions and the DB is the durable
record.

### State machine

    pending ──(start)──> running ──(step N ok)──> running …
                                └── requires review ──> paused_awaiting_input
                                                          └── (resume) ──> running
                                └── step fails ──> failed (terminal)
                         └── all steps done ──> completed (terminal)

- `paused_awaiting_input` can be resumed from only by a Preparer /
  Reviewer action delivered via the API (POST /workflows/{run_id}/
  resume). The runner checks the pause reason (which role must act)
  and rejects resume attempts from the wrong role.
- `failed` is terminal; retry is a new run, not a mutation of the
  failed one. Keeps the failure audit trail honest.
- `completed` is terminal; derived state (export emitted, binder
  assembled) is persisted by the last step, not re-derivable from
  run state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID


class WorkflowState(str, Enum):
    """Terminal + non-terminal states for a workflow run."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED_AWAITING_INPUT = "paused_awaiting_input"
    COMPLETED = "completed"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in {WorkflowState.COMPLETED, WorkflowState.FAILED}

    @property
    def can_advance(self) -> bool:
        """True if the next-step dispatch is allowed from this state."""
        return self in {WorkflowState.PENDING, WorkflowState.RUNNING}


@dataclass
class WorkflowRun:
    """One execution of a workflow template for a specific engagement.

    Mirrors the ``workflow_run`` table. Tests use this directly
    without hitting the DB; the runner reconstructs it from
    persisted rows on resume.
    """

    id: UUID
    tenant_id: UUID
    engagement_id: UUID
    template_id: str
    state: WorkflowState
    current_step_index: int
    created_at: datetime
    updated_at: datetime
    # ``pause_reason`` carries the step_type that's waiting and the
    # role required to resume (e.g., {"step_type": "require_preparer_
    # review", "required_role": "preparer"}). Empty dict when running
    # or terminal.
    pause_reason: dict[str, Any] = field(default_factory=dict)
    # ``context`` is the run-scoped blackboard — step outputs
    # accumulate here keyed by step_name. Bounded in size by the
    # step handlers (they only emit ids + small metadata, never
    # parse-result blobs).
    context: dict[str, Any] = field(default_factory=dict)
    # Final error message if state == failed. Otherwise None.
    error: str | None = None


@dataclass
class WorkflowStepRun:
    """One execution attempt of one step within a run.

    Mirrors the ``workflow_step_run`` table. A step that pauses
    produces a row with state=paused; on resume a new row is
    appended for the next attempt. One row per (run, step_name,
    attempt).
    """

    id: UUID
    run_id: UUID
    step_index: int
    step_name: str
    step_type: str
    state: str  # "running" | "completed" | "paused" | "failed"
    started_at: datetime
    ended_at: datetime | None
    attempt: int
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
