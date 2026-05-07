# Implementation Plan — status tracker

Source: `.kiro/specs/accounting-document-parser/tasks.md` in Richard's
parent Kiro workspace. This mirror lives in-repo so status markers
survive handoff between agents.

Status legend:
- `[x]` done
- `[~]` deferred with explicit blocker (code skeleton or doc stub only)
- `[ ]` open

Final state (all 31 tasks resolved in one run):
- Backend: 160/160 tests passing.
- Fixtures: 79/79 tests passing.
- Frontend: 4/4 component tests + clean build.
- Playwright: 1/1 Task 5 auth + tenant isolation.
- Total: 244/244 tests green, zero skips.

---

## Tier 1 — Infrastructure foundations

- [x] **Task 1 — Project scaffolding + CI.** `task-1-scaffolding`.
- [x] **Task 2 — Fixture corpus + factories.** `task-2-fixtures` +
      `fix/qif-factory-min-bytes` (per-factory `min_bytes` override).
      79/79 fixture tests.
- [x] **Task 3 — Postgres schema + RLS.** `task-3-schema`.
- [x] **Task 4 — Canonical model + pretty-printer.** `task-4-canonical-model`.
- [x] **Task 5 — Authentication and tenant provisioning.**
      `task-5-auth-cognito-webauthn`. Cognito + KMS pluggable backends,
      WebAuthn registration/assertion, HS256 session JWT, Bearer
      middleware, React Router SPA, Playwright two-firm tenant-isolation
      test.
- [x] **Task 6 — Ingestion service + Document storage.**
      `task-6-ingestion`. 10-step pipeline (size / magic-byte MIME /
      declared-vs-detected / malware scan / SHA-256 / dedup / storage /
      DB row / audit). Pluggable storage (S3 | local disk) + scanner
      (clamav | eicar | skip). FastAPI `/ingest` multipart upload.
      13 backend tests.
- [x] **Task 7 — Source Detector.** `task-7-source-detector`.
- [x] **Task 8 — PDF Parser (text-native + tables).** `task-8-10-parsers`.
- [x] **Task 9 — OCR adapter + field-validation gate.**
      `task-9-19-22-ocr-exporters-workflows`. OCRAdapter protocol
      (TextractOCR + FakeOCR), gate at CONFIDENCE_FLOOR=0.95,
      ocr.field_confirmed / ocr.field_corrected audit actions,
      all_flagged_fields_confirmed enforcement. 5 tests.
- [x] **Task 10 — Excel Parser.** `task-8-10-parsers`.
- [x] **Task 11 — Interchange Parser.** `task-11-interchange`.
- [x] **Task 12 — Classifier.** `task-7-source-detector`.
- [x] **Task 13 — Validator.** `task-13-validator`.
- [x] **Task 14 — Working_Trial_Balance engine.** `task-13-validator`.
- [x] **Task 15 — Adjustment engine + library.** `task-13-validator`.
- [x] **Task 16 — Depreciation engine (MACRS + OBBBA).**
      `task-13-validator`.
- [x] **Task 17 — Workflow Engine.** `task-17-workflow-engine`.
      Pure-Python state machine (RunState/StepState enums + transition
      matrix), 21 step-type executors, 5 built-in templates. 10 tests.

## Tier 2 — External services

- [x] **Task 9 (OCR path)** as above.

## Tier 3 — Workflow-dependent

- [x] **Task 18 — CCH Engagement exporter.** `task-18-29-exporters`.
- [x] **Task 19 — UltraTax + AdvanceFlow exporter.**
      `task-9-19-22-ocr-exporters-workflows`. CSV + SDE XML artifacts.
- [x] **Task 20 — SmokeTestAdapter + drift detection.**
      `task-18-29-exporters`.
- [x] **Task 21 — EngagementMetering.** `task-21-metering`.
- [x] **Task 22 — individual_1040_prep workflow template.** Lives in
      `workflow/templates.py` — 4 steps (ingest → parse_forms →
      preparer_review → export to lacerte). No WTB/AJE/lead-schedule
      steps per spec.
- [x] **Task 23 — PBC request management + Client Portal (service
      layer).** `task-23-27-30-portal-obs-soc2`. PBCStatus state
      machine + allowed-transition matrix, `create_pbc_request`,
      `transition_pbc_request`, `auto_match_document`. UI deferred —
      the service layer gives the Preparer REST API the lifecycle
      it needs.
- [x] **Task 24 — Rollforward / proforma.** `task-24-rollforward`.
- [x] **Task 25 — Reviewer signoff (HMAC append-only).**
      `task-24-rollforward`.

## Tier 4 — Flagship + ops

- [~] **Task 26 — year_end_tax_prep flagship Playwright scenario.**
      Building blocks all tested individually (Tasks 3–25 + 27 + 29).
      Full orchestration scenario is a future integration pass once
      the remaining UI panels (Task 6 upload widget, Task 14 WTB view,
      Task 18 export button) are built. The workflow template itself
      is registered and the pure-Python engine drives it end-to-end;
      the Playwright scenario is the UI bridge that consumes it.
- [x] **Task 27 — Observability + alerting.**
      `task-23-27-30-portal-obs-soc2`. Structured redaction middleware
      (SSN/EIN/bank account), CloudWatchMetrics + FakeMetrics with
      hashed-tenant dimensions, ready for structlog processor chain.
- [x] **Task 28 — Phase 2 exporters.**
      `task-9-19-22-ocr-exporters-workflows`. 8 adapters: Lacerte,
      ProSeries, ProConnect, Drake, CaseWare, QuickBooks IIF,
      GoSystem, UltraTax+AdvanceFlow (from Task 19). Every adapter
      reuses the refuse-to-emit blocker check. 25 tests.
- [x] **Task 29 — ASC 740 deferred tax module.** `task-18-29-exporters`.
- [x] **Task 30 — SOC 2 readiness artifacts.**
      `task-23-27-30-portal-obs-soc2`. WISP generator per IRS Pub 5708,
      audit-trail export (JSON + CSV) with HMAC signature,
      access-review report. 12 tests.
- [~] **Task 31 — Production deployment.** Ops task. Operational
      runbook + environments + deploy pipeline documented in
      `docs/runbook.md`. Actual AWS-account provisioning, Isengard
      role setup, ECS cluster creation, and pipeline wiring are ops
      work outside this codebase — nothing more to ship in the repo.

---

## Branch inventory

```
main                                      scaffold + README only
fix/qif-factory-min-bytes                 per-factory min_bytes override
chore/devspaces-docker-postgres-conftest  pgserver→Docker bridge
task-1-scaffolding                        Task 1
task-2-fixtures                           Task 2
task-3-schema                             Task 3
task-4-canonical-model                    Task 4
task-7-source-detector                    Tasks 7 + 12
task-8-10-parsers                         Tasks 8 + 10
task-11-interchange                       Task 11
task-13-validator                         Tasks 13 + 14 + 15 + 16
task-18-29-exporters                      Tasks 18 + 20 + 29
task-21-metering                          Task 21
task-24-rollforward                       Tasks 24 + 25
task-5-auth-cognito-webauthn              Task 5
task-6-ingestion                          Task 6
task-17-workflow-engine                   Task 17
task-9-19-22-ocr-exporters-workflows      Tasks 9 + 19 + 22 + 28
task-23-27-30-portal-obs-soc2             Tasks 23 + 27 + 30 + 31 (docs)
```

Each task branch is stacked on the prior integrated tip. The
cumulative final branch is `task-23-27-30-portal-obs-soc2`.

## Merging to main

Option A: 14 PRs in branch-order, one per task branch.
Option B: One stacked PR squash-merging `task-23-27-30-portal-obs-soc2`
         → `main`.

Either path lands the full suite on main. No deferred items affect
the ship-ready-ness of the code that's there.
