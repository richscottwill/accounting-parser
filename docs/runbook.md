# Operational Runbook

**Scope:** Task 31 deployment + ops scenarios. Covers the day-2 operations
an operator needs after a production deploy: incident response, routine
maintenance, common-failure recovery.

This file is intentionally check-list style so on-call can follow without
reading narrative.

---

## 1. Environments

| Env       | AWS account    | Access                 | Purpose                                 |
|-----------|----------------|------------------------|-----------------------------------------|
| dev       | local + LS     | `docker compose up`    | Engineer laptops, LocalStack backend.   |
| staging   | AWS staging    | Isengard — single approval | Full AWS footprint; weekly prod snapshot. |
| prod      | AWS production | Isengard — dual approval   | Customer-facing. Break-glass only.      |

Break-glass procedure for prod:
1. File a SIM ticket with the change request and blast radius.
2. Get a second engineer approval via Consensus.
3. Assume the `prod-break-glass` role for ≤ 1 hour.
4. Every action is auto-recorded to `platform_audit_log` + CloudTrail.

---

## 2. Deploy

Trunk-based. Main branch is always deployable.

```
$ git checkout main
$ git pull --rebase
$ git tag release-YYYYMMDD-HHMM
$ git push --tags
```

The tag push triggers GitHub Actions:
1. Run full suite (backend + fixtures + frontend + Playwright).
2. Build container image; push to ECR.
3. Run Alembic migrations against staging.
4. Deploy api + worker-parse + worker-export + scheduler to staging.
5. Smoke-test staging.
6. On success, promote to prod canary (10% traffic, 30 min).
7. On success, promote to 100% prod.

Rollback:
```
$ aws ecs update-service --cluster prod --service api \
    --task-definition arn:aws:ecs:...task-definition/api:N-1 \
    --force-new-deployment
```
N-1 = the task-definition revision before the current one.

**Destructive migrations:** forbidden in the normal deploy path. They
run in a two-deploy fence — first deploy writes to both old + new, second
deploy reads from new + drops old.

---

## 3. Common incidents

### 3.1 Audit chain verifier mismatch (SEV-1)

Symptom: scheduler alarm `AuditChainVerifierFailed`.

Action:
1. Stop all writers immediately: `aws ecs update-service --cluster prod
   --service api --desired-count 0`.
2. Identify the affected Tenant from the alarm payload.
3. Pull last 1000 entries: `platform_admin` query →
   `SELECT * FROM audit_log_entry WHERE tenant_id = '...' ORDER BY
   sequence_number DESC LIMIT 1000`.
4. Recompute each `payload_hash` offline and find the break point.
5. File a critical-incident SIM ticket. Do not restart writers until
   the cause is understood and documented.

### 3.2 Cross-tenant data exposure alarm (SEV-1)

Impossible under RLS + api-dispatcher-check + HS256 token signature —
so if this alarm fires, treat as a platform-level compromise until
proven otherwise. Follow the incident response plan in the WISP.

### 3.3 Export adapter drift (SEV-2)

Symptom: `SmokeTestAdapter` flags a target as `at_risk` or `blocked`.

Action:
1. Pull the last successful smoke-test output and diff against the
   current output.
2. Check the vendor's release notes for a format change.
3. Update the affected `TargetSystemAdapter`, run smoke test manually,
   deploy via the normal pipeline.
4. If the adapter's state has moved to `blocked`, production exports
   to that target are already refused — Firms see a banner. Resolve
   within 48 hours to avoid missed Preparer deadlines.

### 3.4 Parse queue backed up (SEV-2)

Symptom: queue depth > 1000 for 30 minutes.

Action:
1. Check `worker-parse` ECS service task count and CPU/memory.
2. Scale out via `aws ecs update-service --desired-count N`.
3. Check Textract / Azure DI availability.
4. If due to a single corrupted Document, quarantine it and re-queue
   the rest.

### 3.5 Midway cookie expiry (dev)

Not a prod path. On DevSpaces, if Slack / SharePoint / Outlook MCPs
return 401:
1. `mwinit -f` to refresh cookie.
2. `brazil-package-cache stop && brazil-package-cache start`.
3. Reload MCPs from the Kiro panel (Ctrl+Shift+P → "MCP: Reload server").

---

## 4. Routine maintenance

- **Weekly:** smoke-test every target adapter (scheduled job).
- **Weekly:** audit-chain verifier walks every Tenant's chain end-to-end.
- **Monthly:** access-review report to Firm administrators.
- **Quarterly:** internal tenant-isolation red team (see
  `docs/security/red-team-exercise.md` — TBD).
- **Annually:** KMS key rotation (automated by AWS).
- **Annually:** third-party penetration test.

---

## 5. Chaos tests

Run in staging before each quarterly release:
- Kill a random `worker-parse` mid-parse; assert the job retries.
- Kill the Postgres primary; assert multi-AZ failover within 60s.
- Saturate 100 concurrent uploads across 10 Tenants; assert zero
  cross-tenant leakage and parse success rate ≥ 99% for Tier-1 sources.
- Delete a LocalStack S3 bucket mid-export; assert the exporter
  retries and rolls back cleanly.

---

## 6. Compliance on-demand artifacts

All generated by `accounting_parser.compliance.*` modules:

- `generate_wisp_for_firm(tenant_id, firm_id)` → Markdown WISP per
  IRS Pub 5708.
- `export_audit_trail_json/csv(tenant_id, start, end)` → tenant-scoped
  audit feed, signed via `sign_export_hmac()`.
- `access_review_report(tenant_id, start, end)` → per-user activity
  counts for SOC 2 periodic access review.

Firm administrators download via the Compliance page in the SPA.
Operators expose them via the internal admin CLI.
