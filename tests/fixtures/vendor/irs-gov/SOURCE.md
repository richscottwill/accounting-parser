# vendor/irs-gov

Official IRS form PDFs downloaded from irs.gov.

## License

Works produced by the United States Government are **public domain** under [17 U.S.C. § 105](https://www.law.cornell.edu/uscode/text/17/105). They can be reproduced, redistributed, and modified without restriction. IRS forms are a classic example.

## Files

| Filename        | Form                                             | Source URL                                    | Downloaded   |
| --------------- | ------------------------------------------------ | --------------------------------------------- | ------------ |
| `fw2.pdf`       | Form W-2 — Wage and Tax Statement                | https://www.irs.gov/pub/irs-pdf/fw2.pdf       | 2026-05-05   |
| `fw9.pdf`       | Form W-9 — Request for Taxpayer ID and Cert.     | https://www.irs.gov/pub/irs-pdf/fw9.pdf       | 2026-05-05   |
| `f1099nec.pdf`  | Form 1099-NEC — Nonemployee Compensation         | https://www.irs.gov/pub/irs-pdf/f1099nec.pdf  | 2026-05-05   |
| `f1099msc.pdf`  | Form 1099-MISC — Miscellaneous Information       | https://www.irs.gov/pub/irs-pdf/f1099msc.pdf  | 2026-05-05   |
| `f1099div.pdf`  | Form 1099-DIV — Dividends and Distributions      | https://www.irs.gov/pub/irs-pdf/f1099div.pdf  | 2026-05-05   |
| `f1099int.pdf`  | Form 1099-INT — Interest Income                  | https://www.irs.gov/pub/irs-pdf/f1099int.pdf  | 2026-05-05   |
| `f1065sk1.pdf`  | Schedule K-1 (Form 1065) — Partner's Share       | https://www.irs.gov/pub/irs-pdf/f1065sk1.pdf  | 2026-05-05   |
| `f1120ssk.pdf`  | Schedule K-1 (Form 1120-S) — Shareholder's Share | https://www.irs.gov/pub/irs-pdf/f1120ssk.pdf  | 2026-05-05   |

## How these are used

- **Parser tests (Task 8 text-native, Task 9 OCR):** these official PDFs contain the real field labels, box positions, and AcroForm field trees the parser has to locate. Committing them ensures the parser is tested against the actual IRS layout, not just our synthetic approximations.
- **Source detection fingerprints (Task 7):** the IRS form PDFs carry `/Producer`, `/Creator`, and AcroForm field-tree signatures the Source_Detector uses. Real-world fingerprints can't be approximated.
- **Synthetic factories (`factories/irs_form_pdf.py`):** our synthetic forms have deliberately-fake data in obvious-fake patterns. The real IRS PDFs committed here are blank templates — no taxpayer data, no PII. Both are used; they exercise different code paths.

## Refresh protocol

IRS updates form PDFs each tax year. When the project rolls to a new tax year:

1. Re-download each file from `https://www.irs.gov/pub/irs-pdf/<filename>`.
2. Compare SHA-256 against the prior-year version. If changed, the tax year on the form has bumped — update any parser tests that pin on tax-year strings.
3. Update the "Downloaded" column in this table with the new date.
