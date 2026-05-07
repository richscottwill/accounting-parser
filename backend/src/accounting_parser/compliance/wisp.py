"""WISP generator — structured sections per IRS Publication 5708.

https://www.irs.gov/pub/irs-pdf/p5708.pdf

The generated WISP is a first draft populated with Firm-specific details
(name, PTIN, admin email). Firm compliance owners complete the narrative
sections and sign. The System's job is to eliminate the blank-page step.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


# Section templates per IRS Pub 5708.
_SECTIONS: list[tuple[str, str]] = [
    (
        "1. Purpose and Scope",
        "The Firm's Written Information Security Plan (WISP) protects client "
        "taxpayer data under the FTC Safeguards Rule and IRS Publications 4557 "
        "and 5708. This WISP applies to every Firm employee, contractor, and "
        "system that processes taxpayer PII.",
    ),
    (
        "2. Designation of a Security Coordinator",
        "The Firm designates {admin_name} (PTIN {admin_ptin_masked}, "
        "{admin_email}) as Security Coordinator, responsible for implementing, "
        "maintaining, and updating this WISP.",
    ),
    (
        "3. Risk Assessment",
        "The Firm has assessed risks to client data at the administrative, "
        "technical, and physical layers. Annual risk re-assessment is "
        "performed at minimum; a re-assessment is triggered by any material "
        "change in IT systems or vendor relationships.",
    ),
    (
        "4. Information Security Safeguards",
        "Administrative: documented incident response, MFA for admin roles, "
        "annual security training. Technical: TLS 1.2+ in transit, "
        "AES-256 with per-Tenant KMS CMK at rest, RLS-enforced tenant "
        "isolation. Physical: locked office storage, device encryption on "
        "every workstation.",
    ),
    (
        "5. Employee Training",
        "Every employee completes annual security training covering PII "
        "handling, phishing recognition, and incident reporting. Records are "
        "retained for at least 7 years.",
    ),
    (
        "6. Vendor / Service-Provider Oversight",
        "The Firm uses AWS (storage + compute), and professional tax/workpaper "
        "systems. Each vendor maintains its own SOC 2 or equivalent attestation.",
    ),
    (
        "7. Incident Response",
        "On discovery of suspected data incident: (1) isolate affected systems, "
        "(2) notify Security Coordinator within 1 hour, (3) file FTC Data "
        "Breach Notification within 30 days if > 500 taxpayers, (4) notify "
        "affected clients per applicable state laws.",
    ),
    (
        "8. Retention + Disposal",
        "Taxpayer data is retained for minimum 7 years from the later of the "
        "Tax_Year filing date or Engagement close. Disposal uses NIST 800-88 "
        "Clear standards for media and cryptographic erasure for cloud data.",
    ),
    (
        "9. Plan Review",
        "This WISP is reviewed annually and after any material change in the "
        "Firm's IT infrastructure or vendor set.",
    ),
]


@dataclass
class WISPContext:
    firm_name: str
    admin_name: str
    admin_email: str
    admin_ptin_masked: str


def generate_wisp_markdown(ctx: WISPContext) -> str:
    """Return the populated WISP as Markdown."""
    header = [
        f"# Written Information Security Plan",
        f"",
        f"**Firm:** {ctx.firm_name}  ",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}  ",
        f"**Source:** IRS Publication 5708 template, populated by "
        "accounting-parser.",
        "",
    ]
    body: list[str] = []
    for title, template in _SECTIONS:
        body.append(f"## {title}")
        body.append("")
        body.append(
            template.format(
                admin_name=ctx.admin_name,
                admin_email=ctx.admin_email,
                admin_ptin_masked=ctx.admin_ptin_masked or "N/A",
            )
        )
        body.append("")
    return "\n".join(header + body)


def generate_wisp_for_firm(
    session: Session, *, tenant_id: UUID, firm_id: UUID
) -> str:
    """Pull Firm + first admin user, produce the WISP Markdown."""
    firm_row = session.execute(
        text("SELECT name FROM firm WHERE id = :i"),
        {"i": str(firm_id)},
    ).mappings().first()
    admin_row = session.execute(
        text(
            """
            SELECT email, ptin_masked, email AS name
            FROM app_user
            WHERE firm_id = :f AND role = 'firm_administrator'
            ORDER BY id LIMIT 1
            """
        ),
        {"f": str(firm_id)},
    ).mappings().first()
    if firm_row is None or admin_row is None:
        raise KeyError(f"firm/admin not found for tenant {tenant_id}")
    ctx = WISPContext(
        firm_name=firm_row["name"],
        admin_name=admin_row["name"],
        admin_email=admin_row["email"],
        admin_ptin_masked=admin_row.get("ptin_masked") or "",
    )
    return generate_wisp_markdown(ctx)
