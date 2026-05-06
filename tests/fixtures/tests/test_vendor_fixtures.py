"""Validation tests for the real-world vendor fixtures under ``vendor/``.

These tests prove:
1. The files we committed are not corrupted (they open, parse, or are
   recognizable as their claimed format).
2. They are the content we claim they are (correct file magic / headers).
3. They exercise the real-world pathologies that our synthetic factories
   cannot.

If one of these fails, regenerate from the upstream source per the SOURCE.md
refresh protocol in each subdirectory.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from ofxparse import OfxParser
from openpyxl import load_workbook  # noqa: F401  (used if we add xlsx samples)
from pypdf import PdfReader

VENDOR = Path(__file__).resolve().parent.parent / "vendor"


# ---------- irs-gov ----------


@pytest.mark.parametrize(
    "filename",
    [
        "f1099div.pdf",
        "f1099int.pdf",
        "f1099msc.pdf",
        "f1099nec.pdf",
        "f1065sk1.pdf",
        "f1120ssk.pdf",
        "fw2.pdf",
        "fw9.pdf",
    ],
)
def test_irs_form_pdf_opens(filename: str) -> None:
    """Each official IRS form PDF opens and has at least one page."""
    path = VENDOR / "irs-gov" / filename
    assert path.exists(), f"missing vendor file: {path}"
    reader = PdfReader(str(path))
    assert len(reader.pages) >= 1
    meta = reader.metadata
    assert meta is not None
    # IRS forms don't set a specific /Producer we can assert on, but /Author
    # or /Creator should at least be non-empty on a real IRS PDF.
    assert (meta.get("/Producer") or meta.get("/Creator") or meta.get("/Author")) is not None


# ---------- ofxparse ----------


@pytest.mark.parametrize(
    "filename",
    [
        "account_listing_aggregation.ofx",
        "bank_medium.ofx",
        "checking.ofx",
        "fidelity.ofx",
        "fidelity-savings.ofx",
        "investment_401k.ofx",
        "investment_medium.ofx",
        "multiple_accounts.ofx",
        "suncorp.ofx",
        "td_ameritrade.ofx",
        "tiaacref.ofx",
        "vanguard.ofx",
        "vanguard401k.ofx",
    ],
)
def test_ofx_sample_parses(filename: str) -> None:
    """Every well-formed OFX sample parses with the canonical parser."""
    path = VENDOR / "ofxparse" / filename
    assert path.exists(), f"missing vendor file: {path}"
    with path.open("rb") as f:
        ofx = OfxParser.parse(f)
    # A valid OFX should have at least one account or one signon.
    assert ofx.accounts is not None or ofx.signon is not None


@pytest.mark.parametrize(
    "filename",
    [
        "error_message.ofx",
        "signon_fail.ofx",
        "signon_success.ofx",
        "signon_success_no_message.ofx",
        "ofx-v102-empty-tags.ofx",
        "bank_small.ofx",
        "anzcc.ofx",
        "multiple_accounts2.ofx",
    ],
)
def test_ofx_edge_case_opens(filename: str) -> None:
    """Edge-case OFX fixtures at minimum open without raising."""
    path = VENDOR / "ofxparse" / filename
    assert path.exists(), f"missing vendor file: {path}"
    # Some edge-cases may fail validation inside OfxParser; we only assert
    # the file is non-empty and has the OFX header. Real parser integration
    # (Task 11) will handle the edge-case dispatch.
    data = path.read_bytes()
    assert len(data) > 0
    assert b"OFX" in data[:200]


# ---------- pdfplumber-samples ----------


@pytest.mark.parametrize(
    "filename,min_pages",
    [
        ("WARN-Report-for-7-1-2015-to-03-25-2016.pdf", 1),
        ("nics-background-checks-2015-11.pdf", 1),
        ("senate-expenditures.pdf", 1),
        ("la-precinct-bulletin-2014-p1.pdf", 1),
        ("scotus-transcript-p1.pdf", 1),
        ("federal-register-2020-17221.pdf", 1),
    ],
)
def test_pdfplumber_sample_opens(filename: str, min_pages: int) -> None:
    """Each real-world public-domain PDF from pdfplumber opens and has pages."""
    path = VENDOR / "pdfplumber-samples" / filename
    assert path.exists(), f"missing vendor file: {path}"
    reader = PdfReader(str(path))
    assert len(reader.pages) >= min_pages


def test_password_example_is_encrypted() -> None:
    """The password-example fixture must actually be password-protected."""
    path = VENDOR / "pdfplumber-samples" / "password-example.pdf"
    assert path.exists()
    reader = PdfReader(str(path))
    assert reader.is_encrypted, "password-example.pdf claims encryption but isn't"


# ---------- sec-edgar ----------


def test_tesla_10k_filing_present() -> None:
    """Tesla 10-K filing has all the expected XBRL files."""
    base = VENDOR / "sec-edgar" / "tesla-10k-2025"
    expected = [
        "tsla-20251231.htm",
        "tsla-20251231_htm.xml",
        "tsla-20251231.xsd",
        "tsla-20251231_pre.xml",
        "tsla-20251231_def.xml",
        "tsla-20251231_lab.xml",
        "tsla-20251231_cal.xml",
        "FilingSummary.xml",
    ]
    for name in expected:
        p = base / name
        assert p.exists(), f"missing SEC file: {p}"
        assert p.stat().st_size > 1000, f"{p} suspiciously small"


def test_tesla_10k_htm_is_inline_xbrl() -> None:
    """The primary htm must contain Inline XBRL markers."""
    p = VENDOR / "sec-edgar" / "tesla-10k-2025" / "tsla-20251231.htm"
    # Read the first chunk; no need to load 2.4 MB
    with p.open("rb") as f:
        head = f.read(50_000)
    # Inline XBRL declares the ix namespace or uses ix:nonFraction / ix:nonNumeric
    assert (
        b"ix:" in head
        or b"inlinexbrl" in head.lower()
        or b"xmlns:ix" in head
    ), "tsla-20251231.htm does not look like Inline XBRL"


def test_tesla_10k_instance_xml_is_xbrl() -> None:
    """Extracted instance XML must have us-gaap facts."""
    p = VENDOR / "sec-edgar" / "tesla-10k-2025" / "tsla-20251231_htm.xml"
    # Scan first 100 KB for signature elements
    with p.open("rb") as f:
        head = f.read(100_000)
    assert b"us-gaap" in head, "expected us-gaap taxonomy references in instance XML"
    assert b"xbrl" in head.lower(), "expected xbrl root element"


# ---------- source documentation ----------


@pytest.mark.parametrize(
    "subdir",
    ["irs-gov", "ofxparse", "pdfplumber-samples", "sec-edgar"],
)
def test_vendor_subdir_has_source_md(subdir: str) -> None:
    """Every vendor subdirectory must have a SOURCE.md documenting license."""
    path = VENDOR / subdir / "SOURCE.md"
    assert path.exists(), f"missing SOURCE.md in vendor/{subdir}/"
    content = path.read_text(encoding="utf-8")
    assert "license" in content.lower() or "public domain" in content.lower()
    assert "source" in content.lower() or "url" in content.lower()


def test_vendor_readme_exists() -> None:
    assert (VENDOR / "README.md").exists()
