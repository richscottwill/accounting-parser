# vendor/sec-edgar

Real-world SEC EDGAR filings in inline XBRL format.

## License

**Public domain.** SEC filings are public records by law. Anyone can download, redistribute, and use them without restriction. See: https://www.sec.gov/os/accessing-edgar-data and 17 U.S.C. § 105 (works of the US Government).

## Subdirectory: `tesla-10k-2025/`

**Filing**: Tesla, Inc. Form 10-K for the fiscal year ended December 31, 2025
**Accession number**: 0001628280-26-003952
**Filed**: 2026-01-29
**CIK**: 0001318605

### Source

- **Canonical URL**: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001318605&type=10-K
- **Filing index**: https://www.sec.gov/Archives/edgar/data/1318605/000162828026003952/
- **Downloaded**: 2026-05-05

### Files

| Filename                  | Contents                                           | Size      |
| ------------------------- | -------------------------------------------------- | --------- |
| `tsla-20251231.htm`       | Inline XBRL 10-K filing (human + machine readable) | 2.4 MB    |
| `tsla-20251231_htm.xml`   | Extracted XBRL instance document                   | 2.7 MB    |
| `tsla-20251231.xsd`       | Company-specific XBRL taxonomy extension           | 103 KB    |
| `tsla-20251231_pre.xml`   | Presentation linkbase (ordering)                   | 829 KB    |
| `tsla-20251231_def.xml`   | Definition linkbase (hierarchy)                    | 539 KB    |
| `tsla-20251231_lab.xml`   | Label linkbase (human-readable names)              | 1.2 MB    |
| `tsla-20251231_cal.xml`   | Calculation linkbase (arithmetic relationships)    | 165 KB    |
| `FilingSummary.xml`       | Filing summary index                               | 61 KB     |

Total: ~8 MB.

### Why this matters for accounting-parser

Inline XBRL is the SEC's standard format for annual/quarterly financial reports. Task 11's XBRL parser has to handle real filings, not just a minimal synthetic XBRL instance. This Tesla filing exercises:

- A real, in-use **US-GAAP taxonomy** with company-specific extensions
- **Inline XBRL** embedded in HTML (the modern format — single document is both human- and machine-readable)
- All five **linkbase types** (presentation, definition, label, calculation, and the instance itself)
- Real-world **facts**: revenue ≈ $98B, assets ≈ $130B, income statement, balance sheet, cash-flow statement, notes
- **Segment reporting** and **consolidation** tagging (exercises context-ref chaining)

If Arelle can't resolve this filing against a real US-GAAP taxonomy, the Task 11 implementation isn't finished.

### Compliance

The SEC requires a **User-Agent header** identifying the requester on any EDGAR request. When downloading, we used:

```
User-Agent: accounting-parser test-fixtures admin@example.com
```

If re-downloading, substitute an appropriate identifying email. Excessive unauthenticated requests are rate-limited.

### Refresh protocol

Tesla will file a new 10-K each January/February. To update to a newer filing:

1. Hit `https://data.sec.gov/submissions/CIK0001318605.json` with a compliant User-Agent.
2. Find the most recent `10-K` form in `filings.recent`.
3. Update the accession number and file list above.
4. Re-download; the file naming pattern `tsla-YYYYMMDD_*` follows the period-end date.
