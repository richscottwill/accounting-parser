# Implementation Plan — status tracker

Source: `.kiro/specs/accounting-document-parser/tasks.md` in Richard's
parent Kiro workspace. This mirror lives in-repo so the status markers
survive handoff between agents.

Status legend:
- `[x]` done
- `[~]` deferred with explicit blocker
- `[ ]` open (should be none at any stable checkpoint)

Work log:
- kiro-local (Windows, no Docker): scaffolded Tasks 1–4, 7–8, 10–16, 18,
  20–21, 24–25, 29 as stacked feature branches. 88 backend tests + 79
  fixture tests green against pgserver.
- kiro-server (DevSpaces, this session): Task 5 end-to-end; pgserver →
  Docker Postgres bridge; fix/qif min_bytes fixup; in-repo mirror of this
  tasks.md for future agents.

---

## Tier 1 — Infrastructure foundations

- [x] **Task 1 — Project scaffolding + CI.** `task-1-scaffolding` branch.
- [x] **Task 2 — Fixture corpus + factories.** `task-2-fixtures` branch.
  - [x] QIF factory / `min_bytes` contradiction resolved on
        `fix/qif-factory-min-bytes`. 79/79 fixture tests green.
- [x] **Task 3 — Postgres schema + RLS.** `task-3-schema` branch.
- [x] **Task 4 — Canonical model + pretty-printer.** `task-4-canonical-model`
      branch.
- [x] **Task 5 — Authentication and tenant provisioning.**
      `task-5-auth-cognito-webauthn` branch.
  - Backend: Cognito pool + KMS adapter (aws|fake backends so dev can
    run against LocalStack Community, which does not ship `cognito-idp`).
    WebAuthn registration + assertion via `python-fido2`. HS256 session
    JWT. Bearer-token middleware that pins `app.tenant_id` per request.
    7 backend tests green.
  - Frontend: React Router v6 with `AuthProvider`, `SignupPage`,
    `LoginPage`, `DashboardPage`, SimpleWebAuthn browser integration.
    4 component tests green.
  - Validation: Playwright `task-5-auth.spec.ts` drives two firms through
    signup with CDP virtual WebAuthn authenticators, asserts cross-
    tenant isolation at the HTTP layer (HS256 tamper rejection, valid
    token returns own identity only). 1 test green.
- [~] **Task 6 — Ingestion service + Document storage.** Blocked on
      ClamAV sidecar + LocalStack S3 + running upload UI.
- [x] **Task 7 — Source Detector.** `task-7-source-detector` branch.
- [x] **Task 8 — PDF Parser (text-native + tables).** `task-8-10-parsers`.
- [~] **Task 9 — PDF Parser OCR + field-validation gate.** Blocked on
      Textract + Azure DI creds + running UI for the gate modal.
- [x] **Task 10 — Excel Parser.** `task-8-10-parsers`.
- [x] **Task 11 — Interchange Parser.** `task-11-interchange`.
- [x] **Task 12 — Classifier.** `task-7-source-detector`.
- [x] **Task 13 — Validator.** `task-13-validator`.
- [x] **Task 14 — Working_Trial_Balance engine.** `task-13-validator`.
- [x] **Task 15 — Adjustment Engine + library.** `task-13-validator`.
- [x] **Task 16 — Depreciation engine (MACRS + OBBBA).** `task-13-validator`.
- [~] **Task 17 — Workflow Engine.** Blocked on Redis + running UI.

## Tier 2 — External services

- [~] **Task 9 (OCR path)** as above.

## Tier 3 — Workflow-dependent

- [x] **Task 18 — CCH Engagement exporter + Dynalink + XTBLink.**
      `task-18-29-exporters`.
- [~] **Task 19 — UltraTax + AdvanceFlow exporter.** Deferred; same
      shape as Task 18.
- [x] **Task 20 — SmokeTestAdapter + drift detection.**
      `task-18-29-exporters`.
- [x] **Task 21 — EngagementMetering.** `task-21-metering`.
- [~] **Task 22 — individual_1040_prep workflow template.** Blocked on
      Task 17 + Task 9.
- [~] **Task 23 — PBC request management + Client Portal.** Blocked on
      running Client SPA + second Cognito pool.
- [x] **Task 24 — Rollforward / proforma.** `task-24-rollforward`.
- [x] **Task 25 — Reviewer signoff (HMAC append-only).**
      `task-24-rollforward`.

## Tier 4 — Flagship + ops

- [~] **Task 26 — year_end_tax_prep flagship Playwright scenario.**
      Blocked on Tasks 6, 17, 22, 23.
- [~] **Task 27 — Observability + alerting.** Blocked on AWS + PagerDuty.
- [~] **Task 28 — Phase 2 exporters.** Sandbox-access gated.
- [x] **Task 29 — ASC 740 deferred tax module.** `task-18-29-exporters`.
- [~] **Task 30 — SOC 2 readiness artifacts.** Blocked on running UI.
- [~] **Task 31 — Production deployment.** Ops task.

---

## Branch inventory (as of Task 5 completion)

```
main                                     scaffold + README only (2 commits)
fix/qif-factory-min-bytes                inherits task-2-fixtures base
chore/devspaces-docker-postgres-conftest inherits task-18-29-exporters tip
task-1-scaffolding                       Task 1
task-2-fixtures                          Task 2
task-3-schema                            Task 3 (depends on task-2)
task-4-canonical-model                   Task 4 (depends on task-3)
task-7-source-detector                   Tasks 7 + 12
task-8-10-parsers                        Tasks 8 + 10
task-11-interchange                      Task 11
task-13-validator                        Tasks 13 + 14 + 15 + 16
task-18-29-exporters                     Tasks 18 + 20 + 29   ← cumulative integrated tip
task-21-metering                         Task 21
task-24-rollforward                      Tasks 24 + 25
task-5-auth-cognito-webauthn             Task 5               ← current work
```

`main` is intentionally scaffold-only. Each task branch is stacked on
the prior one in the order above; `task-18-29-exporters` carries every
merged dependency. Task 5 branches off `chore/devspaces-docker-postgres-
conftest` (which branches off `task-18-29-exporters`), so it sees the
full integrated tree.

When opening a PR, open 14 PRs against `main` in the order above, or
squash-merge the whole stack via `task-5-auth-cognito-webauthn → main`
once review is done.
