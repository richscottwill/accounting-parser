# tests/fixtures/vendor

Vendor-published or public-domain reference documents.

## What's here

### `irs-gov/` — Public domain ✓

Official IRS form PDFs downloaded from irs.gov. Works of the US Government are public domain under [17 U.S.C. § 105](https://www.law.cornell.edu/uscode/text/17/105) — free to reproduce and redistribute without restriction. See `irs-gov/SOURCE.md` for the full manifest and refresh protocol.

## What's deliberately absent

Task 2 of the implementation plan originally called for loading "vendor-published sample files where public" from the tax-software vendors. After research:

- **CCH Axcess Engagement** — Wolters Kluwer publishes a free downloadable "Trial Balance Worksheet" on bizfilings.com, but it is a generic BizFilings tool, not the CCH Axcess Engagement import template. Sample import templates ship only inside licensed Engagement installs and are subject to Wolters Kluwer's license terms.
- **Thomson Reuters AdvanceFlow / UltraTax CS** — No publicly-redistributable sample files. Help documentation only.
- **Intuit QuickBooks** — Sample companies are accessible via the live web sandbox at `qbo.intuit.com/redir/testdrive`. No downloadable company file.
- **Intuit Lacerte** — Sample templates ship only inside licensed installs.

Committing vendor-licensed samples to a public GitHub repo would violate their license terms. Our factories in `../factories/` produce structurally-equivalent synthetic approximations following the vendors' publicly-documented import-template specs (column order, header names, expected data types).

## The real acceptance gate for vendor exports

Our synthetic fixtures test *our* side of the export. Before promoting a Task 18-20 exporter (CCH Engagement, UltraTax + AdvanceFlow, Lacerte) to production, the generated export file must be **manually round-tripped through a licensed sandbox** of the target vendor system. That's the only way to confirm we're emitting the shape the vendor actually accepts.

## Adding more vendor content

If a vendor publishes a freely-redistributable sample file with an explicit license (e.g., a public GitHub repo under a permissive license, or a Creative Commons grant), add it here:

1. Create a subdirectory named after the vendor, e.g. `vendor/wolters-kluwer/`.
2. Add a `SOURCE.md` with the download URL, date pulled, license text or link, and any attribution required.
3. Commit the sample file.

Do not commit vendor-copyrighted content without an explicit written license permitting redistribution.
