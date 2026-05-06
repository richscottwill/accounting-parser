"""CLI entry point: generate the full fixture corpus.

Run from ``tests/fixtures/`` with Poetry:

    poetry run python generate_all.py [--output-dir OUT]

Writes ~20 fixture files into ``OUT`` (default: ``generated/``). Re-running
is idempotent — files are overwritten deterministically.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from factories.bank_statement_pdf import bank_statement_pdf_factory
from factories.cch_engagement_xlsx import cch_engagement_import_xlsx_factory
from factories.fixed_assets_xlsx import fixed_asset_schedule_factory
from factories.interchange import (
    iif_factory,
    ofx_factory,
    qfx_factory,
    qif_factory,
    xbrl_factory,
)
from factories.irs_form_pdf import irs_form_pdf_factory
from factories.netsuite_tb_xlsx import netsuite_tb_xlsx_factory
from factories.prior_year_return_pdf import prior_year_1120s_factory
from factories.qbd_gl_pdf import qbd_gl_pdf_factory
from factories.qbo_tb_pdf import qbo_tb_pdf_factory
from factories.rejection_samples import (
    corrupted_pdf_factory,
    corrupted_xlsx_factory,
    image_only_scan_pdf_factory,
    password_protected_pdf_factory,
    password_protected_xlsx_factory,
)
from factories.sage_intacct_tb_pdf import sage_intacct_tb_pdf_factory
from factories.xero_tb_xlsx import xero_tb_xlsx_factory


def generate_all(output_dir: Path) -> list[Path]:
    """Generate every fixture into ``output_dir``. Returns the list of paths."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []

    # TB / GL PDFs
    paths.append(qbo_tb_pdf_factory(output_dir / "qbo_trial_balance.pdf"))
    paths.append(qbd_gl_pdf_factory(output_dir / "qbd_general_ledger.pdf"))
    paths.append(sage_intacct_tb_pdf_factory(output_dir / "sage_intacct_trial_balance.pdf"))

    # TB XLSX
    paths.append(xero_tb_xlsx_factory(output_dir / "xero_trial_balance.xlsx"))
    paths.append(netsuite_tb_xlsx_factory(output_dir / "netsuite_trial_balance.xlsx"))

    # Template XLSX (empty)
    paths.append(cch_engagement_import_xlsx_factory(output_dir / "cch_engagement_template.xlsx"))

    # IRS forms
    paths.append(irs_form_pdf_factory(
        "W-2",
        output_dir / "sample_w2.pdf",
        fields={
            "1": "45,678.90", "2": "6,789.01", "3": "45,678.90", "4": "2,832.09",
            "5": "45,678.90", "6": "662.34", "15": "WA", "16": "0.00", "17": "0.00",
            "b": "00-0000000",
            "c": "Synthetic Demo Co, LLC\n100 Fake St\nSeattle, WA 98101",
            "e": "Jane Q. Employee",
        },
    ))
    paths.append(irs_form_pdf_factory(
        "1099-NEC", output_dir / "sample_1099_nec.pdf",
        fields={"1": "12,345.67", "4": "0.00", "payer-tin": "00-0000000"},
    ))
    paths.append(irs_form_pdf_factory(
        "1099-MISC", output_dir / "sample_1099_misc.pdf",
        fields={"1": "23,456.78", "2": "0.00", "3": "0.00", "4": "0.00"},
    ))
    paths.append(irs_form_pdf_factory(
        "K-1-1065", output_dir / "sample_k1_1065.pdf",
        fields={"1": "56,789.01", "5": "1,234.56", "6a": "789.01", "14": "56,789.01"},
    ))
    paths.append(irs_form_pdf_factory(
        "K-1-1120S", output_dir / "sample_k1_1120s.pdf",
        fields={"1": "112,233.32", "5a": "3,456.78", "17-AC": "112,233.32"},
    ))

    # Bank statements
    paths.append(bank_statement_pdf_factory("Chase", output_dir / "chase_bank_statement.pdf"))
    paths.append(bank_statement_pdf_factory("BoA", output_dir / "boa_bank_statement.pdf"))

    # Prior-year return
    paths.append(prior_year_1120s_factory(output_dir / "prior_year_1120s.pdf"))

    # Fixed asset schedule
    paths.append(fixed_asset_schedule_factory(output_dir / "fixed_asset_schedule.xlsx"))

    # Interchange
    paths.append(ofx_factory(output_dir / "sample.ofx"))
    paths.append(qfx_factory(output_dir / "sample.qfx"))
    paths.append(qif_factory(output_dir / "sample.qif"))
    paths.append(iif_factory(output_dir / "sample.iif"))
    paths.append(xbrl_factory(output_dir / "sample.xbrl"))

    # Rejection-path
    paths.append(password_protected_pdf_factory(output_dir / "password_protected.pdf"))
    paths.append(password_protected_xlsx_factory(output_dir / "password_protected.xlsx"))
    paths.append(corrupted_pdf_factory(output_dir / "corrupted.pdf"))
    paths.append(corrupted_xlsx_factory(output_dir / "corrupted.xlsx"))
    paths.append(image_only_scan_pdf_factory(output_dir / "image_only_scan.pdf"))

    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the accounting-parser fixture corpus.")
    parser.add_argument("--output-dir", type=Path, default=Path("generated"),
                        help="Output directory (default: ./generated)")
    args = parser.parse_args()

    paths = generate_all(args.output_dir)
    print(f"Generated {len(paths)} fixtures in {args.output_dir.resolve()}:")
    for p in sorted(paths):
        print(f"  {p.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
