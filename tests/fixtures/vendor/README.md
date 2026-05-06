# tests/fixtures/vendor

Vendor-published, public-domain, or openly-licensed reference documents used by `accounting-parser` tests.

## What's here

### `irs-gov/` — Public domain (US Government, 17 USC §105)

8 official IRS form PDFs: W-2, W-9, 1099-NEC/MISC/DIV/INT, Schedule K-1 for Forms 1065 and 1120-S. See `irs-gov/SOURCE.md`.

### `ofxparse/` — MIT License

21 real-world OFX test fixtures from `jseutter/ofxparse`. Bank statements, credit cards, savings, 401(k)s, investment accounts, error paths, vendor-specific quirks. See `ofxparse/SOURCE.md`.

### `pdfplumber-samples/` — MIT + public-domain government documents

7 real-world public-domain PDFs from `jsvine/pdfplumber` tests. California WARN Report, FBI NICS background checks, Senate expenditures, LA precinct bulletin, SCOTUS transcript, Federal Register document, password-protected sample. See `pdfplumber-samples/SOURCE.md`.

### `sec-edgar/` — Public domain (SEC filings)

Real SEC EDGAR inline XBRL filings. Currently: Tesla Form 10-K for FY 2025 (~8 MB, 8 files). See `sec-edgar/SOURCE.md`.

## What's deliberately absent

Tax-software vendor templates from:

- **CCH Axcess Engagement** (Wolters Kluwer)
- **Thomson Reuters AdvanceFlow / UltraTax CS**
- **Intuit QuickBooks** (sample companies are live web sandbox only)
- **Intuit Lacerte**

Sample templates from these vendors ship only inside licensed installs and are not freely redistributable. Our factories in `../factories/` produce synthetic approximations following each vendor's publicly-documented import-template specs. The real acceptance gate for Tasks 18-20 exporters is manual round-trip through a licensed vendor sandbox.

## Corpus statistics

| Directory              | Files  | Total size  | Source reliability        |
| ---------------------- | ------ | ----------- | ------------------------- |
| `irs-gov/`             | 8      | ~3.6 MB     | Official IRS              |
| `ofxparse/`            | 21     | ~55 KB      | MIT OSS, canonical tests  |
| `pdfplumber-samples/`  | 7      | ~1.5 MB     | MIT OSS + US/CA gov       |
| `sec-edgar/tesla-10k-2025/` | 8  | ~8 MB       | Official SEC filing       |
| **Totals**             | **44** | **~13 MB**  |                           |

## Adding more vendor content

If a vendor publishes freely-redistributable sample files with an explicit license:

1. Create a subdirectory named after the vendor, e.g. `vendor/<vendor-slug>/`.
2. Add `SOURCE.md` with: download URL, download date, license text or link, file manifest with sizes and purposes, refresh protocol.
3. Commit the sample files.

Do not commit vendor-copyrighted content without an explicit written license permitting redistribution.

## Why vendor samples matter

The synthetic factories in `../factories/` produce idealised documents — clean grammar, consistent formatting, predictable values. Real-world documents have ugly edge cases: page rotations, column-boundary quirks, embedded fonts that break text extraction, encrypted content, multi-byte character encodings, vendor-specific dialect variations.

Every downstream parser (Tasks 8-11) that passes synthetic-factory tests but fails against the files in this directory has a real-world defect. These files are the regression benchmark.
