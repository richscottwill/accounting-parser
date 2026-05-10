"""Workflow engine — orchestrates multi-step engagement pipelines.

Parent spec R10 + fork P1.4. The workflow engine owns:

- Step registry (``StepRegistry``) — the set of step types a
  workflow can use. Built-in: parse, classify, validate,
  require_preparer_review, require_reviewer_signoff,
  post_adjustments, emit_export.
- Workflow template definitions (``WorkflowTemplate``) — a named
  ordered list of steps. First template: ``monthly_close_bookkeeping``.
- Execution state machine (``WorkflowState``): pending → running →
  paused_awaiting_input → completed / failed.
- Runner (``WorkflowRunner``) — iterates steps, handles pause
  semantics, persists state to the ``workflow_run`` table.
- Celery task wrapper (``start_workflow_run`` +
  ``advance_workflow_run``) — lets the API layer kick off runs
  and lets the pause/resume UI resume them.

Pure state-machine logic is testable without Celery; the Celery
wrapper is a thin adapter.
"""

from accounting_parser.workflow.registry import (
    BuiltinStepType,
    StepContext,
    StepHandler,
    StepRegistry,
    StepResult,
    StepStatus,
)
from accounting_parser.workflow.runner import WorkflowRunner, WorkflowRunView
from accounting_parser.workflow.state import WorkflowRun, WorkflowState, WorkflowStepRun
from accounting_parser.workflow.templates import (
    WorkflowStepDef,
    WorkflowTemplate,
    get_template,
    monthly_close_bookkeeping,
    register_template,
)

__all__ = [
    "BuiltinStepType",
    "StepContext",
    "StepHandler",
    "StepRegistry",
    "StepResult",
    "StepStatus",
    "WorkflowRun",
    "WorkflowRunView",
    "WorkflowRunner",
    "WorkflowState",
    "WorkflowStepDef",
    "WorkflowStepRun",
    "WorkflowTemplate",
    "get_template",
    "monthly_close_bookkeeping",
    "register_template",
]
