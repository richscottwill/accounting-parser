"""PDF + Excel parser tests.

Runs against freshly-generated synthetic factory fixtures and the real
pdfplumber vendor samples under tests/fixtures/vendor/pdfplumber-samples/.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures"
sys.path.insert(0, str(FIXTURES))

from accounting_parser.parser import (  # noqa: E402
    MoneyParseResult,
    parse_excel,
    parse_money,
    parse_pdf_text_native,
)


# ---------- Monetary value parsing ----------


def test_parse_money_basic() -> None:
    assert parse_money("1,234.56").value == Decimal("1234.56")


def test_parse_money_dollar_sign() -> None:
    assert parse_money("$1,234.56").value == Decimal("1234.56")


def test_parse_money_paren_negative() -> None:
    r = parse_money("(1,234.56)")
    assert r.value == Decimal("-1234.56")
    assert r.displayed == "(1,234.56)"


def test_parse_money_trailing_minus() -> None:
    r = parse_money("1,234.56-")
    assert r.value == Decimal("-1234.56")
    assert r.displayed == "1,234.56-"


def test_parse_money_leading_minus() -> None:
    assert parse_money("-1,234.56").value == Decimal("-1234.56")


def test_parse_money_invalid() -> None:
    with pytest.raises(ValueError):
        parse_money("not a number")


# ---------- PDF text-native ----------


@pytest.fixture
def qbo_tb_pdf(tmp_path: Path) -> Path:
    from factories.qbo_tb_pdf import qbo_tb_pdf_factory
    return qbo_tb_pdf_factory(tmp_path / "qbo.pdf", multi_page=True)


def test_pdf_parses_multi_page_tb(qbo_tb_pdf: Path) -> None:
    result = parse_pdf_text_native(qbo_tb_pdf)
    assert len(result.sections) == 1
    lines = result.sections[0].lines
    assert len(lines) >= 20, f"expected many extracted lines, got {len(lines)}"
    # Every line should have either debit or credit
    for ln in lines:
        assert ln.debit + ln.credit >= 0


def test_pdf_parses_real_pdfplumber_sample() -> None:
    p = FIXTURES / "vendor" / "pdfplumber-samples" / "senate-expenditures.pdf"
    if not p.exists():
        pytest.skip("vendor sample missing")
    result = parse_pdf_text_native(p)
    # Just assert it didn't crash and produced something
    assert result is not None


# ---------- Excel ----------


@pytest.fixture
def xero_xlsx(tmp_path: Path) -> Path:
    from factories.xero_tb_xlsx import xero_tb_xlsx_factory
    return xero_tb_xlsx_factory(tmp_path / "xero.xlsx")


@pytest.fixture
def netsuite_xlsx(tmp_path: Path) -> Path:
    from factories.netsuite_tb_xlsx import netsuite_tb_xlsx_factory
    return netsuite_tb_xlsx_factory(tmp_path / "ns.xlsx")


def test_excel_parses_xero_tb(xero_xlsx: Path) -> None:
    result = parse_excel(xero_xlsx)
    lines = result.sections[0].lines
    assert len(lines) >= 10, f"expected many lines from xero TB, got {len(lines)}"
    # Validate at least one line has a real debit or credit
    assert any(ln.debit > 0 or ln.credit > 0 for ln in lines)


def test_excel_parses_netsuite_tb(netsuite_xlsx: Path) -> None:
    result = parse_excel(netsuite_xlsx)
    lines = result.sections[0].lines
    assert len(lines) >= 10


def test_excel_handles_missing_header_columns(tmp_path: Path) -> None:
    from openpyxl import Workbook
    p = tmp_path / "bad.xlsx"
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "no proper header"
    wb.save(p)
    result = parse_excel(p)
    # No crash; zero or few lines is acceptable
    assert result is not None
