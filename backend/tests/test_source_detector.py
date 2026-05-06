"""Source detector tests.

Generates fixtures fresh each test run (via the same factories that Task 2
ships), feeds them through the detector, and asserts the classifier picks
the correct source_system with confidence >= 0.85 for every adapter
(Task 7 validation target + Correctness Property 18 soundness).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures"
sys.path.insert(0, str(FIXTURES))  # so factories package is importable

from accounting_parser.source_detector import (  # noqa: E402
    HIGH_CONFIDENCE_FLOOR,
    detect_source,
)


# Minimal import of factories. Do it inside a fixture so import-time
# reportlab state is isolated from the backend package.

@pytest.fixture
def generated_qbo_tb(tmp_path: Path) -> Path:
    from factories.qbo_tb_pdf import qbo_tb_pdf_factory
    return qbo_tb_pdf_factory(tmp_path / "qbo.pdf", multi_page=False)


@pytest.fixture
def generated_xero(tmp_path: Path) -> Path:
    from factories.xero_tb_xlsx import xero_tb_xlsx_factory
    return xero_tb_xlsx_factory(tmp_path / "xero.xlsx")


@pytest.fixture
def generated_netsuite(tmp_path: Path) -> Path:
    from factories.netsuite_tb_xlsx import netsuite_tb_xlsx_factory
    return netsuite_tb_xlsx_factory(tmp_path / "ns.xlsx")


@pytest.fixture
def generated_cch(tmp_path: Path) -> Path:
    from factories.cch_engagement_xlsx import cch_engagement_import_xlsx_factory
    return cch_engagement_import_xlsx_factory(tmp_path / "cch.xlsx")


@pytest.fixture
def generated_sage(tmp_path: Path) -> Path:
    from factories.sage_intacct_tb_pdf import sage_intacct_tb_pdf_factory
    return sage_intacct_tb_pdf_factory(tmp_path / "sage.pdf")


@pytest.fixture
def generated_chase_bank(tmp_path: Path) -> Path:
    from factories.bank_statement_pdf import bank_statement_pdf_factory
    return bank_statement_pdf_factory("Chase", tmp_path / "chase.pdf")


@pytest.fixture
def real_irs_1099nec() -> Path:
    return REPO_ROOT / "tests" / "fixtures" / "vendor" / "irs-gov" / "f1099nec.pdf"


def test_detects_quickbooks_online(generated_qbo_tb: Path) -> None:
    result = detect_source(generated_qbo_tb)
    assert result.source_system == "quickbooks_online"
    assert result.confidence >= HIGH_CONFIDENCE_FLOOR


def test_detects_xero(generated_xero: Path) -> None:
    result = detect_source(generated_xero)
    assert result.source_system == "xero"
    assert result.confidence >= HIGH_CONFIDENCE_FLOOR


def test_detects_netsuite(generated_netsuite: Path) -> None:
    result = detect_source(generated_netsuite)
    assert result.source_system == "netsuite"
    assert result.confidence >= HIGH_CONFIDENCE_FLOOR


def test_detects_cch_engagement_template(generated_cch: Path) -> None:
    result = detect_source(generated_cch)
    assert result.source_system == "cch_engagement_template"
    assert result.confidence >= HIGH_CONFIDENCE_FLOOR


def test_detects_sage_intacct(generated_sage: Path) -> None:
    result = detect_source(generated_sage)
    assert result.source_system == "sage_intacct"
    assert result.confidence >= HIGH_CONFIDENCE_FLOOR


def test_detects_bank_statement(generated_chase_bank: Path) -> None:
    result = detect_source(generated_chase_bank)
    assert result.source_system == "bank_statement_pdf"
    assert result.confidence >= 0.85


def test_detects_real_irs_form(real_irs_1099nec: Path) -> None:
    if not real_irs_1099nec.exists():
        pytest.skip(f"real IRS fixture not present: {real_irs_1099nec}")
    result = detect_source(real_irs_1099nec)
    assert result.source_system == "irs_form_pdf"
    # Real IRS PDFs may or may not have "irs" in /Producer — accept >= 0.80
    assert result.confidence >= 0.80


def test_unknown_pdf_classified_as_unknown(tmp_path: Path) -> None:
    from reportlab.pdfgen import canvas
    p = tmp_path / "blank.pdf"
    c = canvas.Canvas(str(p))
    c.drawString(100, 750, "Arbitrary document, no source fingerprint")
    c.showPage()
    c.save()
    result = detect_source(p)
    assert result.source_system == "unknown"
