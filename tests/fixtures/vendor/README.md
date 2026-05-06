# tests/fixtures/vendor

**This directory is intentionally empty of vendor-published content.**

## Why

Task 2 of the implementation plan calls for loading "vendor-published sample files where public" — specifically Wolters Kluwer CCH Engagement sample TB and Thomson Reuters AdvanceFlow sample spreadsheet.

After reviewing:

- **CCH Axcess Engagement** — sample templates ship inside licensed installs. Wolters Kluwer's license terms restrict redistribution. No publicly-redistributable sample TB has been located.
- **Thomson Reuters AdvanceFlow** — same pattern. Sample spreadsheets require a licensed installation and are not public-domain.
- **UltraTax CS** — same.
- **Lacerte Trial Balance Utility** — same.

Bundling these in a public GitHub repo would violate the vendors' license terms.

## What we do instead

Our factories in `../factories/` produce **structurally equivalent synthetic approximations**:

- `cch_engagement_import_xlsx_factory` emits the documented 13-column layout CCH Engagement accepts (Account Number, Account Name, Account Type, Prior Year, Unadjusted, AJE, Adjusted, RJE, Final, TJE, Tax Basis, FS Grouping, Tax Grouping). Column order and header names match CCH's publicly-documented import template. Cell formatting and styling approximate the real template but are not copies.
- AdvanceFlow, UltraTax, Lacerte equivalents are generated from their respective publicly-documented import-template specs (to be added in Tasks 18-20 when those exporters ship).

## Acceptance path

Before promoting a Task 18/19 exporter to production, the generated export file must be **manually round-tripped through a licensed sandbox** of the target vendor system. That's the real acceptance gate. Synthetic fixtures test our side; a vendor round-trip tests theirs.

## If vendor-published public samples surface

If Wolters Kluwer or Thomson Reuters ever publish freely-redistributable sample files with explicit permission (e.g., via a public GitHub repo under a permissive license), add them here with:

1. A subdirectory named after the vendor, e.g. `vendor/wolters-kluwer/`
2. A `SOURCE.md` file in that subdirectory noting the download URL, the date pulled, the license, and any attribution required
3. Commit the sample itself

Until then, this directory stays empty.
