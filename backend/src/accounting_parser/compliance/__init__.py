"""Compliance artifact generators (P2.4).

Produces four artifacts a CPA firm needs for regulatory posture:

- R31.1: WISP PDF per IRS Pub 5708 structure.
- R31.2: Audit trail export (JSON + CSV) signed with the Firm
  master key via HMAC — chain-of-custody preserved.
- R31.3: Access review report — every User + every Client they
  accessed in a window.
- R31.4: Data inventory report — every Document per Client with
  metadata.

Plus R31.5: the ``docs/compliance/subprocessor-disclosure.md``
static file shipped with the installer (not a runtime artifact).

### Design posture

Every artifact is produced as bytes in memory and returned to the
caller, not written to disk. Routes stream to the HTTP client; CLI
tools pipe to ``>`` or ``mc cp``. Nothing about the generation path
touches the filesystem, which keeps tests self-contained and
simplifies per-firm retention policy (the bytes are ephemeral).
"""

from accounting_parser.compliance.access_review import AccessReviewEntry, generate_access_review
from accounting_parser.compliance.audit_export import (
    AuditExportBundle,
    export_audit_trail,
    verify_audit_export,
)
from accounting_parser.compliance.data_inventory import DataInventoryEntry, generate_data_inventory
from accounting_parser.compliance.wisp import WispContext, generate_wisp_markdown

__all__ = [
    "AccessReviewEntry",
    "AuditExportBundle",
    "DataInventoryEntry",
    "WispContext",
    "export_audit_trail",
    "generate_access_review",
    "generate_data_inventory",
    "generate_wisp_markdown",
    "verify_audit_export",
]
