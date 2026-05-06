# vendor/pdfplumber-samples

Real-world public-domain PDFs from the `jsvine/pdfplumber` test corpus.

## License

Two layers:

1. **pdfplumber test corpus itself**: MIT License — Copyright (c) 2015 Jeremy Singer-Vine. Full text: https://github.com/jsvine/pdfplumber/blob/stable/LICENSE.txt
2. **Underlying documents**: each PDF is a public record from a US or state government body. Works of the US Government are public domain under [17 U.S.C. § 105](https://www.law.cornell.edu/uscode/text/17/105). California public records are likewise generally available for use.

## Source

- **Repo**: https://github.com/jsvine/pdfplumber
- **Path**: `tests/pdfs/`
- **Commit**: `stable` branch (downloaded 2026-05-05)

## Files

| Filename                                          | Source document                                                | Why it's useful                               |
| ------------------------------------------------- | -------------------------------------------------------------- | --------------------------------------------- |
| `WARN-Report-for-7-1-2015-to-03-25-2016.pdf`      | California EDD WARN Act Report                                 | Multi-page tabular layout with line items     |
| `nics-background-checks-2015-11.pdf`              | FBI NICS Firearm Background Check statistics                   | Multi-column per-state tables                 |
| `senate-expenditures.pdf`                         | US Senate expenditures report                                  | Tabular financial line items                  |
| `la-precinct-bulletin-2014-p1.pdf`                | LA County precinct bulletin                                    | Dense tabular data with multi-row cells       |
| `scotus-transcript-p1.pdf`                        | US Supreme Court oral argument transcript                      | Double-column layout, text extraction edge cases |
| `federal-register-2020-17221.pdf`                 | US Federal Register document 2020-17221                        | Long, text-dense government document          |
| `password-example.pdf`                            | Synthetic password-protected PDF                               | Ingestion rejection-path fixture              |

## Attribution

When referring to these files in commits or documentation, credit Jeremy Singer-Vine and the `pdfplumber` project for curating them and pdfplumber's test suite for the selection.

## Why these matter for accounting-parser

Government financial/administrative PDFs have the exact pathologies our parser must handle:

- **CA WARN Report**: multi-page tables that continue across page breaks (exercises header-row duplicate-suppression from Task 8).
- **NICS Background Checks**: multi-column per-state tables (exercises column-boundary detection via x-axis clustering).
- **Senate Expenditures**: financial amounts with parenthesis-negatives, commas, dollar signs (exercises monetary-value parsing).
- **LA Precinct Bulletin**: dense tabular layout with merged cells in the visual sense (exercises cluster separation logic).
- **SCOTUS Transcript**: two-column text layout (exercises the multi-column detection branch from Task 8).
- **Federal Register**: long text-dense document (exercises the text-native fast path; no table extraction needed).
- **password-example.pdf**: standalone rejection-path fixture alongside our synthetic one.

Task 8 (PDF parser, text-native path) should run against all 7 of these files as smoke tests before being considered production-ready.

## Refresh protocol

Same as for `vendor/ofxparse/SOURCE.md`. pdfplumber's test corpus evolves slowly; pinning to `stable` branch at download date is the right default.
