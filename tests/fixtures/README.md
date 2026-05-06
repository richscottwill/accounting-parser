# tests/fixtures

Synthetic accounting-document fixtures for the accounting-parser test suite.

**Every file in this directory is synthetic. No real taxpayer data, no PII, no copyrighted vendor content.** Numeric values use obvious-fake patterns like `$12,345.67` so accidental exposure during screenshots is visually detectable.

## Quick start

```bash
cd tests/fixtures
poetry install
poetry run python generate_all.py --output-dir generated
```

This writes ~26 fixtures into `generated/`. That directory is gitignored — regenerate on demand.

## Layout

| Path                    | Contents                                         |
| ----------------------- | ------------------------------------------------ |
| `factories/`            | Python factories that emit synthetic fixtures    |
| `vendor/`               | Public-domain & licensed vendor reference files  |
| `vendor/irs-gov/`       | 8 official IRS form PDFs (public domain)         |
| `generated/`            | Output of `generate_all.py` (gitignored)         |
| `pyproject.toml`        | Poetry project for factory deps (reportlab, openpyxl, pypdf, Pillow, cryptography) |

## Fixture manifest

| Filename                         | Produced by                      | Exercises req. |
| -------------------------------- | -------------------------------- | -------------- |
| `qbo_trial_balance.pdf`          | `qbo_tb_pdf_factory`             | R2.1, R4.1, R4.12 |
| `qbd_general_ledger.pdf`         | `qbd_gl_pdf_factory`             | R2.1, R4.6 (landscape two-column) |
| `sage_intacct_trial_balance.pdf` | `sage_intacct_tb_pdf_factory`    | R2.1, R4.1 |
| `xero_trial_balance.xlsx`        | `xero_tb_xlsx_factory`           | R2.1, R5.1 |
| `netsuite_trial_balance.xlsx`    | `netsuite_tb_xlsx_factory`       | R2.1, R5.1 |
| `cch_engagement_template.xlsx`   | `cch_engagement_import_xlsx_factory` | R17.1 (synthetic approximation) |
| `sample_w2.pdf`                  | `irs_form_pdf_factory("W-2")`    | R4.2, R4.24 |
| `sample_1099_nec.pdf`            | `irs_form_pdf_factory("1099-NEC")` | R4.2 |
| `sample_1099_misc.pdf`           | `irs_form_pdf_factory("1099-MISC")` | R4.2 |
| `sample_k1_1065.pdf`             | `irs_form_pdf_factory("K-1-1065")` | R4.2 |
| `sample_k1_1120s.pdf`            | `irs_form_pdf_factory("K-1-1120S")` | R4.2 |
| `chase_bank_statement.pdf`       | `bank_statement_pdf_factory("Chase")` | R4.11, R2.1 |
| `boa_bank_statement.pdf`         | `bank_statement_pdf_factory("BoA")`   | R4.11, R2.1 |
| `prior_year_1120s.pdf`           | `prior_year_1120s_factory`       | R19 (rollforward), R22 (prior-year) |
| `fixed_asset_schedule.xlsx`      | `fixed_asset_schedule_factory`   | R13.1, R13.9, OBBBA boundary |
| `sample.ofx`                     | `ofx_factory`                    | R6.1 |
| `sample.qfx`                     | `qfx_factory`                    | R6.1 |
| `sample.qif`                     | `qif_factory`                    | R6.1 |
| `sample.iif`                     | `iif_factory`                    | R6.1 |
| `sample.xbrl`                    | `xbrl_factory`                   | R6.1 |
| `password_protected.pdf`         | `password_protected_pdf_factory` | R1.5, R5.23 |
| `password_protected.xlsx`        | `password_protected_xlsx_factory` | R5.23 |
| `corrupted.pdf`                  | `corrupted_pdf_factory`          | R1.6 |
| `corrupted.xlsx`                 | `corrupted_xlsx_factory`         | R1.6 |
| `image_only_scan.pdf`            | `image_only_scan_pdf_factory`    | R4.1, R4.11, R4.24 (OCR gate) |

## Determinism

Every factory is deterministic: same inputs = byte-identical output. This lets Task 4's Correctness-Property 3 test (byte-identical pretty-printing) stand on stable fixtures.

## Adding a factory

1. Create `factories/<new_source>.py` with a single `<name>_factory(output_path, **kwargs) -> Path` function.
2. Export it from `factories/__init__.py`.
3. Wire it into `generate_all.py`.
4. Add a row to the manifest above.
5. Run the factory-level test: `poetry run pytest tests/` inside `tests/fixtures/`.

## Spot-check protocol

Task 2's `[Validate]` sub-step requires a one-time human spot-check: open three random PDFs and three random XLSX files and confirm they look plausible in Adobe Reader / Excel. Record the check in `tests/fixtures/spot-check-log.md` with the date and your name.
