"""WISP (Written Information Security Plan) generator — R31.1.

Produces a Markdown document populated per the IRS Publication 5708
structure. The Markdown is rendered to PDF by the caller's
documentation pipeline (or imported into the firm's own WISP binder
verbatim).

### Why Markdown not ReportLab PDF

1. A CPA firm's legal counsel wants to edit the WISP; Markdown
   preserves that workflow.
2. Generating PDF requires a native dep (ReportLab + layout tuning)
   that's heavy for a runtime artifact. Phase 3's installer can ship
   pandoc if the firm wants PDF.
3. The substantive content is what matters for compliance — format
   is secondary and negotiable with the firm's counsel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class WispContext:
    """Firm-specific fields that populate the WISP.

    Populated by the caller from ``firm`` + ``tenant`` rows + the
    deployment's Settings (backup paths, offsite config, etc.).
    Every field has a default so the template never panics on
    missing data; unfilled fields render as ``[TO BE COMPLETED]``
    placeholders which is the correct behavior for a draft the firm
    principal will review.
    """

    firm_name: str = "[TO BE COMPLETED]"
    firm_administrator_name: str = "[TO BE COMPLETED]"
    firm_administrator_email: str = "[TO BE COMPLETED]"
    host_os: str = "[TO BE COMPLETED]"
    deployment_address: str = "[TO BE COMPLETED]"
    backup_schedule: str = "nightly at 02:00 local time"
    backup_retention_days: int = 30
    offsite_backup_target: str | None = None
    data_retention_years: int = 7
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


_TEMPLATE = """\
# Written Information Security Plan

**Firm:** {firm_name}
**Administrator:** {firm_administrator_name} ({firm_administrator_email})
**Deployment:** {deployment_address} (host OS: {host_os})
**Generated:** {generated_at}

This plan follows the structure of IRS Publication 5708, *Creating a
Written Information Security Plan for your Tax & Accounting Practice*.

## 1. Designated Security Coordinator

The firm's designated security coordinator is {firm_administrator_name}.
The coordinator is responsible for implementing, monitoring, and
updating the safeguards described below.

## 2. Risk Assessment

The firm has identified the following risks to taxpayer information
under its custody:

- Unauthorized access to the accounting-parser deployment.
- Loss of the master passphrase, rendering sealed secrets
  unrecoverable (documented in the installer).
- Backup media theft or destruction.
- Malware infection of the Firm_Instance host.
- Unauthorized use of firm credentials.

The firm reviews this risk list at least annually, and after any
material change to its systems or procedures.

## 3. Administrative Safeguards

- The Firm Administrator and every user are identified by name,
  role, and passkey credential; passwords are disabled by default
  per R26.2.
- Access to taxpayer data is granted on a per-Client basis; the
  application enforces Client-level isolation within the firm.
- Every authentication event, document upload, and workflow state
  transition is audit-logged; the audit chain is tamper-evident via
  SHA-256 hash chaining.
- Staff receive annual training on the firm's security obligations
  under IRS Circular 230 and the FTC Safeguards Rule.

## 4. Technical Safeguards

- The Firm master key is 256-bit; it is sealed with Argon2id +
  AES-256-GCM using a passphrase memorized by the Firm Administrator.
- Per-Client data encryption keys are derived from the master via
  HKDF-SHA256.
- TLS terminates at the firm's reverse proxy; all internal service
  traffic is confined to the Docker network.
- Virus scanning (ClamAV) runs on every upload before the document
  is made available to parsers.

## 5. Physical Safeguards

- The Firm_Instance host is located at {deployment_address}.
- Physical access is restricted to {firm_administrator_name} and
  explicitly-authorized personnel.
- Backup media (local + optional offsite target {offsite_backup_target})
  is stored in a locked cabinet or encrypted offsite location.

## 6. Incident Response

The firm maintains an incident response procedure covering
- Suspected unauthorized access or data breach.
- Loss of master passphrase.
- Ransomware or destructive malware.
- Backup restoration drills (quarterly).

The IRS Stakeholder Liaison is notified within 24 hours of any
confirmed breach affecting taxpayer information per IRS guidance.

## 7. Backup and Recovery

- Schedule: {backup_schedule}.
- Local retention: {backup_retention_days} days of daily backups,
  plus monthly backups retained indefinitely.
- Offsite target: {offsite_backup_target_display}.
- Quarterly restore drill: a randomly selected backup is decrypted
  to a throwaway host and verified to produce an equivalent
  Firm_Instance (CP30).

## 8. Data Retention and Disposal

- Audit log: retained indefinitely (append-only; schema enforces).
- Parse results and canonical model snapshots: retained
  {data_retention_years} years from Engagement close.
- Documents: retained per the firm's configurable document-
  retention policy (default {data_retention_years} years from
  Engagement close).
- Destruction: secrets are zeroized on service shutdown; documents
  are deleted from MinIO and referenced audit log entries are
  redacted but not removed.

## 9. Third-Party Service Providers

No third-party service provider processes taxpayer information on
the firm's behalf unless the firm has explicitly opted in (e.g.,
by configuring AWS Textract for OCR under R29.2). The firm maintains
a current written agreement with any such provider.

## 10. Annual Review

This WISP is reviewed and updated annually, or whenever the firm
makes a material change to its systems or procedures. The most
recent generated version bears the timestamp at the top of this
document.

---

*This document was generated by accounting-parser {firm_instance_version}
and must be reviewed by the firm's designated security coordinator
before being considered current.*
"""


def generate_wisp_markdown(ctx: WispContext, *, firm_instance_version: str = "0.2.0") -> str:
    """Render the WISP Markdown for ``ctx``.

    Returns a ``str`` — caller writes to disk or streams. Offsite
    target is rendered as "none configured" when ctx.offsite_backup_
    target is None so the WISP reads naturally regardless.
    """
    offsite = ctx.offsite_backup_target or "none configured"
    return _TEMPLATE.format(
        firm_name=ctx.firm_name,
        firm_administrator_name=ctx.firm_administrator_name,
        firm_administrator_email=ctx.firm_administrator_email,
        deployment_address=ctx.deployment_address,
        host_os=ctx.host_os,
        backup_schedule=ctx.backup_schedule,
        backup_retention_days=ctx.backup_retention_days,
        offsite_backup_target=ctx.offsite_backup_target or "[TO BE COMPLETED]",
        offsite_backup_target_display=offsite,
        data_retention_years=ctx.data_retention_years,
        generated_at=ctx.generated_at,
        firm_instance_version=firm_instance_version,
    )
