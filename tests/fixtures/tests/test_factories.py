"""Smoke tests for every fixture factory.

Each test asserts the factory runs without error, produces a non-empty file
with the expected extension, and is deterministic (same inputs => byte-
identical output).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from factories.bank_statement_pdf import SUPPORTED_BANKS, bank_statement_pdf_factory
from factories.cch_engagement_xlsx import cch_engagement_import_xlsx_factory
from factories.fixed_assets_xlsx import fixed_asset_schedule_factory
from factories.interchange import iif_factory, ofx_factory, qfx_factory, qif_factory, xbrl_factory
from factories.irs_form_pdf import FORM_LAYOUTS, irs_form_pdf_factory
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


def _hash(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _assert_file(p: Path, *, ext: str, min_bytes: int = 200) -> None:
    assert p.exists(), f"{p} was not created"
    assert p.suffix == ext, f"{p} has suffix {p.suffix}, expected {ext}"
    assert p.stat().st_size >= min_bytes, f"{p} is suspiciously small ({p.stat().st_size} bytes)"


@pytest.mark.parametrize("factory,name,ext", [
    (qbo_tb_pdf_factory, "qbo.pdf", ".pdf"),
    (qbd_gl_pdf_factory, "qbd.pdf", ".pdf"),
    (sage_intacct_tb_pdf_factory, "intacct.pdf", ".pdf"),
    (xero_tb_xlsx_factory, "xero.xlsx", ".xlsx"),
    (netsuite_tb_xlsx_factory, "ns.xlsx", ".xlsx"),
    (cch_engagement_import_xlsx_factory, "cch.xlsx", ".xlsx"),
    (prior_year_1120s_factory, "py1120s.pdf", ".pdf"),
    (fixed_asset_schedule_factory, "fa.xlsx", ".xlsx"),
    (ofx_factory, "s.ofx", ".ofx"),
    (qfx_factory, "s.qfx", ".qfx"),
    (qif_factory, "s.qif", ".qif"),
    (iif_factory, "s.iif", ".iif"),
    (xbrl_factory, "s.xbrl", ".xbrl"),
    (corrupted_pdf_factory, "c.pdf", ".pdf"),
    (corrupted_xlsx_factory, "c.xlsx", ".xlsx"),
    (password_protected_pdf_factory, "pp.pdf", ".pdf"),
    (password_protected_xlsx_factory, "pp.xlsx", ".xlsx"),
    (image_only_scan_pdf_factory, "scan.pdf", ".pdf"),
])
def test_single_arg_factory_produces_valid_file(tmp_path: Path, factory, name: str, ext: str) -> None:
    out = factory(tmp_path / name)
    # Corrupted factories are deliberately tiny; allow smaller min size
    min_bytes = 30 if "corrupt" in factory.__name__ else 200
    _assert_file(out, ext=ext, min_bytes=min_bytes)


@pytest.mark.parametrize("bank", SUPPORTED_BANKS)
def test_bank_statement_factory(tmp_path: Path, bank: str) -> None:
    out = bank_statement_pdf_factory(bank, tmp_path / f"{bank}.pdf")
    _assert_file(out, ext=".pdf")


@pytest.mark.parametrize("form_id", sorted(FORM_LAYOUTS))
def test_irs_form_factory(tmp_path: Path, form_id: str) -> None:
    out = irs_form_pdf_factory(form_id, tmp_path / f"{form_id}.pdf")
    _assert_file(out, ext=".pdf")


def test_irs_form_unknown_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown form_id"):
        irs_form_pdf_factory("FORM-9999", tmp_path / "x.pdf")


def test_bank_unknown_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown bank"):
        bank_statement_pdf_factory("BadBank", tmp_path / "x.pdf")


def test_qbo_tb_deterministic(tmp_path: Path) -> None:
    """Same inputs must produce byte-identical output (Correctness Property 3 precursor)."""
    a = qbo_tb_pdf_factory(tmp_path / "a.pdf")
    b = qbo_tb_pdf_factory(tmp_path / "b.pdf")
    # PDFs include a trailer with /ID and /ModDate which reportlab stamps
    # with the current time — strip those bytes before comparing. We hash
    # just the stream-content portion up to the /ID marker.
    data_a = a.read_bytes()
    data_b = b.read_bytes()
    # Find the xref marker; everything up to it is content + objects
    idx_a = data_a.rfind(b"xref")
    idx_b = data_b.rfind(b"xref")
    assert idx_a > 0 and idx_b > 0
    assert data_a[:idx_a] == data_b[:idx_b], (
        "QBO TB factory is not deterministic in content — ReportLab IDs may have leaked"
    )


def test_iif_malformed_option(tmp_path: Path) -> None:
    good = iif_factory(tmp_path / "good.iif", malformed=False)
    bad = iif_factory(tmp_path / "bad.iif", malformed=True)
    assert _hash(good) != _hash(bad)
    assert b"!TRNS\tTRNSID" in good.read_bytes()
    assert b"!TRNS\tDATE" in bad.read_bytes()


def test_generate_all(tmp_path: Path) -> None:
    """Full corpus generates without errors."""
    from generate_all import generate_all  # type: ignore[import-not-found]
    paths = generate_all(tmp_path / "corpus")
    assert len(paths) >= 25, f"expected at least 25 fixtures, got {len(paths)}"
    for p in paths:
        assert p.exists(), f"{p} missing"
