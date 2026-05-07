"""SOC 2 / Circular 230 / FTC Safeguards compliance artifacts — Task 30.

Produces on-demand artifacts that firms submit to auditors:
- WISP (Written Information Security Plan) populated per IRS Pub 5708
- Audit trail export per time window (JSON + CSV)
- Access review report: every User who touched Firm data in a window
- Data inventory: rows per table + S3 storage per Tenant

All artifacts are tenant-scoped and signed with the System's identity
(HMAC over canonical payload) so a downstream auditor can verify
authenticity.
"""
