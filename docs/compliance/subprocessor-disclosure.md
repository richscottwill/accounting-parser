# Subprocessor Disclosure — accounting-parser (self-hosted fork)

**Purpose:** This document is shipped with the accounting-parser
installer so the CPA firm can include it in its own compliance
documentation (WISP, DPA with clients, Circular 230 disclosures).

**Status:** The accounting-parser software, when deployed on
hardware the firm controls, acts as the firm's internal system —
**not** as a subprocessor under the FTC Safeguards Rule, the IRS
Safeguards Rule (Pub 4557 / Pub 5708), or the AICPA SOC 2 framework.

## What this means

When a firm runs accounting-parser on its own hardware, the software:

- Does not send taxpayer data to the software vendor (Richard
  Williams) unless the firm has explicitly opted into a specific
  feature that does so (e.g., configuring AWS Textract for OCR
  under R29.2; see §3 below).
- Does not connect to any third-party service at runtime except
  - Host NTP (for time synchronization).
  - The update-check endpoint (polling only, no data uploaded).
  - Let's Encrypt ACME (only if the firm configured a public domain
    for TLS).
- Does not mirror any logs, metrics, or data to an external system.
  Prometheus, Grafana, Loki, and Alertmanager all run inside the
  firm's Docker stack and terminate their data on the firm's host.

## 1. Software vendor role

Richard Williams is the software vendor. His relationship with the
firm is covered by a written agreement separate from this document.
Under that agreement Richard:

- Ships signed releases the firm installs.
- Is available for time-limited, firm-initiated support through the
  reverse support tunnel (R30.4). The tunnel is read-only by default;
  every session is audit-logged on the firm's host.
- Does not have standing access to the firm's Firm_Instance.
- Does not receive taxpayer data through any production path.

## 2. Host provider (if any)

If the firm rents a VPS or co-located hardware, the host provider
(e.g., a VPS company, data center operator) is a **subprocessor of
the firm**, not of Richard. The firm selects and contracts with
that provider directly and is responsible for the provider's own
compliance posture.

## 3. Opt-in external services

The firm may enable any of the following on its own initiative.
Each requires the firm to configure credentials; none are enabled
by default. When enabled, the named service becomes a subprocessor
of the firm, and the firm is responsible for maintaining a current
Data Processing Agreement (DPA) with that service.

- **AWS Textract** — OCR alternative under R29.2. Processes
  uploaded document bytes.
- **Azure Document Intelligence** — alternative OCR under R29.2.
- **S3 / Backblaze B2 / Azure Blob / rsync offsite target** —
  encrypted backup replication under R27.3. The bundle is
  encrypted with the firm master key before transmission; the
  offsite provider never sees plaintext but is still in the custody
  chain for the encrypted bundle.
- **Let's Encrypt (via Caddy)** — TLS certificate issuer if the
  firm deploys with a public domain.

## 4. Change history

This document is a static artifact shipped with each release of
the software. When the subprocessor posture changes (e.g., a new
opt-in external service is added or removed), this document is
updated and shipped in the same release. The firm is notified of
the change via the update-check endpoint.

## 5. How to reference this in firm documentation

Firms typically include this disclosure in:

- Section 9 of the firm's WISP (Third-Party Service Providers).
- Schedule A of the firm's DPA with each client.
- Section 4 of the firm's Privacy Policy.

If the firm's counsel requires a different format, they may
reformat this document at will; the substantive content is the
binding statement.
