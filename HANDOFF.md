# Accounting Parser — Handoff to kiro-server (DevSpaces)

**From:** kiro-local (Windows, Kiro IDE local)
**To:** kiro-server (DevSpaces SSH container)
**Date:** 2026-05-05
**Repo:** https://github.com/richscottwill/accounting-parser
**Parent spec:** `.kiro/specs/accounting-document-parser/` in Richard's local workspace
  (mirror into DevSpaces workspace if not already there, or read from there directly)

## TL;DR

kiro-local built the 60% of this project that's pure Python + pgserver on a Windows box with no Docker. **167 tests green (88 backend + 79 fixtures), 9 Correctness Properties verified at 6,500+ Hypothesis examples.** Every task in `tasks.md` is resolved — 14 shipped with `[x]`, 12 marked `[~]` DEFERRED with explicit infrastructure blockers.

Your job, kiro-server, is to pick up the 12 deferred tasks that were blocked on infrastructure kiro-local doesn't have: Docker containers (Postgres + Redis + LocalStack), AWS creds (Cognito, Textract, S3), a running FastAPI + React SPA for Playwright validation, Celery worker, vendor sandboxes.

## What's shipped

Clone the repo:

```bash
git clone https://github.com/richscottwill/accounting-parser.git
cd accounting-parser
git checkout main  # or cherry-pick the per-task branches in merge order
```

Per-task branches (pushed to origin, mergeable in this order):

1. `task-1-scaffolding` — monorepo layout, Poetry, pnpm, pre-commit, GitHub Actions CI, Docker Compose (Postgres 16 + Redis 7 + LocalStack)
2. `task-2-fixtures` — 25 synthetic factories + 44 vendor fixtures (21 OFX from ofxparse MIT, 7 pdfplumber gov PDFs, Tesla 10-K XBRL, 8 IRS forms)
3. `task-3-schema` — Alembic migration with 21 tables, RLS policies, SHA-256 audit hash chain, `app_user` NOBYPASSRLS role
4. `task-4-canonical-model` — Pydantic v2 canonical model + deterministic pretty-printer
5. `task-13-validator` — validator, WTB engine, adjustment library, depreciation engine w/ OBBBA 2025 (tasks 13-16 combined)
6. `task-11-interchange` — OFX/QFX/QIF/IIF/XBRL parsers
7. `task-24-rollforward` — year-over-year rollforward + HMAC reviewer signoff (tasks 24-25 combined)
8. `task-21-metering` — event-sourced monotonic counters
9. `task-7-source-detector` — 9 adapters + rules classifier (tasks 7+12 combined)
10. `task-8-10-parsers` — PDF text-native + Excel parsers
11. `task-18-29-exporters` — CCH Engagement exporter + SmokeTestAdapter + ASC 740 (tasks 18, 20, 29 combined)

**All 88 backend tests pass locally with pgserver (Postgres 16.2 in-process).** When you bring Docker up with the compose file, the same tests should pass against containerised Postgres with no code changes — the session fixture resolves DSN from `ACCOUNTING_PARSER_DB_URL` env var.

## Environment verification (first 10 minutes)

```bash
cd accounting-parser

# 1. Bring up infra (you have Docker; kiro-local did not)
docker compose up -d
docker compose ps                # Postgres 5432, Redis 6379, LocalStack 4566

# 2. Backend deps
cd backend
poetry env use python3.12         # or whatever 3.12 binary DevSpaces provides
poetry install
poetry run pytest --no-cov        # expect 88/88
cd ..

# 3. Frontend deps (only for Task 1 validation baseline)
cd frontend
pnpm install
pnpm test                          # expect 2/2
pnpm build                         # expect clean
cd ..

# 4. Fixture corpus regen
cd tests/fixtures
poetry env use python3.12
poetry install
poetry run pytest                  # expect 79/79
poetry run python generate_all.py --output-dir generated
cd ../..
```

If all four groups exit clean, you've reproduced kiro-local's state and can start on deferred work.

## Deferred tasks — pick up in this order

The order below is dependency-driven. Don't skip ahead.

### Tier 1 — Infrastructure foundations (Tasks 5, 6, 17)

These three unblock everything else. Tier 2 can't start without them.

#### Task 5: Authentication and tenant provisioning

**What kiro-local already did:** `backend/src/accounting_parser/db/session.py` has
`set_tenant_context(session, tenant_id)` that pins `app.tenant_id` per session, plus
`assert_app_user_has_no_bypass_rls()` startup check.

**What you need to add:**

- FastAPI auth middleware that extracts JWT, resolves user → tenant, calls
  `set_tenant_context` on the DB session for every request.
- Cognito user pool creation via LocalStack (preparer pool + client-portal pool).
  The spec calls for two separate pools — keep them separate even at MVP.
- Signup endpoint that bootstraps a Firm, creates a Firm_Administrator user,
  provisions a per-Tenant KMS key alias (LocalStack KMS).
- WebAuthn (passkey) enrollment flow via the `fido2` library (already in deps).
- Frontend: login page, passkey enrollment UI, signup bootstrap.
- **[Validate]** Playwright: two-context test confirming tenant isolation at the
  HTTP/SPA level (separate from the DB-level RLS test kiro-local already wrote
  in `test_rls_tenant_isolation.py`).

_Requirements:_ 1.1, 1.10, 21.1, 21.2, 21.3, 21.5, 21.6.

#### Task 6: Ingestion service and Document storage

- `IngestionService` accepting multipart upload, validating size + MIME (declared
  vs magic-byte detection), computing SHA-256, running ClamAV scan (sidecar
  container in the Docker Compose setup).
- Per-Tenant LocalStack S3 buckets with per-Tenant KMS CMKs.
- Duplicate detection via SHA-256 within `(tenant_id, client_id)`. The
  `document` table already has the `document_dedup_unique` constraint from Task 3
  — hard-reject on insert with a structured error referencing the original
  Document ID.
- Frontend upload widget with drag-drop, progress, post-upload state showing
  detected Source_System from Task 7.
- 5 Playwright validate tasks per spec: happy path, duplicate rejection,
  password-protected rejection, 100MB-over-limit rejection, audit-log verification.

_Requirements:_ 1.1–1.11, 22.1.

#### Task 17: Workflow Engine + monthly_close_bookkeeping

- Celery state machine (pending → running → paused_awaiting_input → completed/failed).
  Redis broker via Docker Compose (already in compose file).
- Step registry with built-in step types (parse, classify, validate,
  require_preparer_review, require_reviewer_signoff, post_adjustments,
  emit_export).
- Pause/resume semantics on the two review steps.
- First workflow template: `monthly_close_bookkeeping` — parse → classify →
  validate → propose month-end accruals → draft financials.
- 2 Playwright validate tasks: walking the workflow end-to-end; confirming
  deliberate validator failure halts subsequent steps.

_Requirements:_ 10.1–10.6, 10.8, 10.11, 10.12.

### Tier 2 — Parsers needing external services (Task 9)

#### Task 9: PDF OCR + field-validation gate

Depends on AWS Textract + Azure Document Intelligence creds. Use the `OCRAdapter`
interface pattern — two implementations that both conform to the same Protocol.
Field-validation gate UI requires the running SPA (Task 6 prereq).

Kiro-local drafted parse_money and the text-native extraction; add the OCR
fallback when a page has < 20 extractable non-whitespace chars, propagate
per-field confidence, build the gate modal that blocks navigation when any
field has confidence < 0.95 until Preparer confirms.

_Requirements:_ 4.1, 4.2, 4.11, 4.19, 4.24.

### Tier 3 — Workflow-dependent tasks (Tasks 19, 22, 23)

After 17, build the remaining exporters and workflow templates.

- **Task 19** — Thomson Reuters UltraTax + AdvanceFlow exporter. Same shape as
  the CCH exporter kiro-local already shipped. Flag the vendor-sandbox
  round-trip as manual gate.
- **Task 22** — `individual_1040_prep` workflow. Simpler than monthly close —
  skip WTB/AJE/lead-schedule steps. Flow: ingest → sub-parsers → field gate →
  emit 1040-shaped export.
- **Task 23** — PBC management + Client Portal. Needs separate Cognito pool,
  magic-link/passkey, client-facing upload UI with auto-matching to outstanding
  PBC_Request. Two-context Playwright test (Preparer + Client).

### Tier 4 — Flagship scenario + operational readiness (Tasks 26, 27, 28, 30, 31)

- **Task 26** — `year_end_tax_prep` 11-step ex-RSM scenario. This is the
  acceptance gate. Every building block exists; the Playwright harness ties
  them together. Must complete in < 30 minutes.
- **Task 27** — Observability. structlog already in deps; add redaction
  middleware (SSN/EIN/bank account/monetary patterns), CloudWatch metrics,
  OpenTelemetry tracing (1% default sample / 100% for debug-header requests),
  PagerDuty tiers.
- **Task 28** — Phase 2 exporters (Lacerte, QuickBooks IIF, CCH ProSystem fx,
  Drake, ProConnect, ProSeries, GoSystem, CaseWare, SafeSend). Each follows
  the Task 18 pattern + SmokeTestAdapter registration.
- **Task 30** — SOC 2 readiness artifacts. WISP generator from IRS Pub 5708,
  audit-trail export signer, access review report.
- **Task 31** — Two-account AWS deploy with dual-approval break-glass, canary
  pipeline, runbooks, chaos tests, load tests (100 concurrent uploads across
  10 tenants with zero cross-tenant leakage), quarterly red-team test.

## Environment quirks you should know

1. **pgserver was kiro-local's escape hatch.** Windows + Amazon corporate
   licensing made Docker Desktop non-viable. `pgserver` is a dev dep on backend
   but tests resolve DSN from env var, so on DevSpaces you can either (a) keep
   pgserver as the test DB (fine, it's just a Python wheel) or (b) point
   `ACCOUNTING_PARSER_DB_URL` at the Docker Compose Postgres and skip the
   pgserver boot entirely. Either works.

2. **`app_user` role and BYPASSRLS startup check.** When migrations run against
   a new database, `app_user` is created with NOBYPASSRLS. The app layer
   refuses to start if that bit drifts — don't manually flip it to "debug
   something." If you need superuser access, connect as `platform_admin`.

3. **Audit log hash chain uses `sha256()` not `pgcrypto::digest()`.** kiro-local
   discovered pgserver doesn't ship `pgcrypto`. PostgreSQL 11+ has `sha256(bytea)`
   in core, and kiro-local used that. If you later want pgcrypto (HMAC,
   random bytes), `CREATE EXTENSION pgcrypto` works on the Docker Postgres
   — but the migration already uses the core function, so don't "fix" what
   isn't broken unless you have a real reason.

4. **CRLF vs LF on fixture files.** `.gitattributes` at repo root pins OFX/XML/
   XBRL/IIF to LF. Don't remove those rules — a stray CRLF breaks hash chain
   verification on round-trip tests.

5. **Vendor samples deliberately absent for some.** `tests/fixtures/vendor/`
   has `irs-gov/` (8 public-domain IRS forms), `ofxparse/` (21 MIT), and
   `pdfplumber-samples/` (7 public-domain US/CA gov PDFs), plus `sec-edgar/
   tesla-10k-2025/` (public SEC filing). CCH / AdvanceFlow / UltraTax / Lacerte
   vendor samples are NOT present — license restrictions. `vendor/README.md`
   documents this. Don't "helpfully" pull them from random GitHub mirrors;
   those mirrors are violating upstream licenses and we'd inherit that problem.

6. **The two kiros' outputs interleave.** If kiro-local ships anything else to
   this repo while you're working, it'll come in via `git pull` with conflicts
   on `tasks.md` only (every other file is branch-owned). Rebase tasks.md
   manually — one row per task.

7. **Five Levels check.** This project is not on Richard's L1-L5 career ladder
   (he's a paid-search marketing manager at Amazon; this is a side project or
   Kiro capability stress test). Flag any hours invested here as opportunity
   cost against the Five Levels. Don't silently spend days on Task 31 chaos
   tests if Richard hasn't asked for them — check in.

## Files to read first (in this order)

1. `.kiro/specs/accounting-document-parser/requirements.md` — 798 lines, R1-R24
2. `.kiro/specs/accounting-document-parser/design.md` — modular monolith on AWS
3. `.kiro/specs/accounting-document-parser/tasks.md` — 31 tasks with status markers
4. `accounting-parser/README.md` — 15-minute bootstrap
5. `accounting-parser/backend/tests/conftest.py` — pgserver session fixture
   pattern (you'll keep or replace per point 1 above)
6. `accounting-parser/tests/fixtures/vendor/README.md` — honest licensing notes

## Correctness properties already verified

Don't re-verify these; trust the existing tests and Hypothesis runs.

| # | Property | Test file | Examples |
|---|---|---|---|
| 1 | Adjustment proposal determinism | `test_adjustments.py::test_deterministic_proposals_correctness_property_1` | 1 |
| 2 | Canonical JSON round-trip under equivalence | `test_canonical_model.py::test_canonical_json_round_trips` | 1000 |
| 3 | Canonical JSON byte-identical across calls | `test_canonical_model.py::test_canonical_json_is_deterministic` | 1000 |
| 6 | RLS tenant isolation | `test_rls_tenant_isolation.py::test_app_user_cannot_see_other_tenant_rows` | 1000 |
| 8 | Audit log hash chain append-only | `test_audit_hash_chain.py::test_audit_log_hash_chain_append_only_and_verifiable` | 1000 entries (100×10) |
| 9 | TB balance or error finding | `test_validator.py::test_tb_either_balances_or_has_error_finding` | 1000 |
| 12 | WTB tie-out invariant | `test_wtb_engine.py::test_wtb_tie_out_invariant` | 1000 |
| 16 | Rollforward preserves beginning=prior_ending | `test_rollforward.py::test_current_beginning_equals_prior_ending` | 50 |
| 19 | Depreciation three-stage ordering + OBBBA | `test_depreciation.py` | 500 each |
| 28 | Metering monotonicity | `test_metering.py::test_sum_increments_is_monotonic` | 100 |

Remaining properties (from requirements.md §Correctness Properties): 4, 5, 7, 10, 11, 13–15, 17, 18, 20–27 — these test flows that span the deferred tasks, so pick them up in the appropriate tier.

## Bus check

If you're reading this via the agent-bus sync, consider posting a reply on the
bus thread when you've reproduced kiro-local's state and are starting Tier 1.
Follow `agent-bus-participation.md` rules. Don't ping-pong — one "ready to
proceed" reply is enough.

---

**When Tier 1 is done, mark tasks 5, 6, 17 as `[x]` in tasks.md, push the
branches with the same conventional-commit pattern kiro-local used, and
update `shared/context/intake/session-log.md` with a one-line status.**
