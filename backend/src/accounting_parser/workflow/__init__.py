"""Workflow engine — sequences Workflow_Steps per Engagement, halts on
failure, pauses for human review.

Implements Task 17.

Components:
- ``state.py``    — run + step-run state machine (pure Python).
- ``registry.py`` — Workflow_Step type registry.
- ``templates.py``— built-in workflow templates (monthly_close, year_end,
                    engagement_review, new_client_onboarding, individual_1040).
- ``engine.py``   — orchestrator: starts runs, executes steps in order,
                    persists state, emits audit.
- ``steps.py``    — step implementations (parse, classify, validate,
                    require_preparer_review, require_reviewer_signoff, ...).

Celery adapter deferred — the pure-Python engine is sufficient for the
step-registry contract and for Task 17's correctness properties. Wrapping
``engine.run_next_step`` in a Celery task is a trivial future addition.
"""
# Import step implementations so they register with the step registry at
# module load. Without this, get_step("ingest") raises KeyError.
from accounting_parser.workflow import steps  # noqa: F401
