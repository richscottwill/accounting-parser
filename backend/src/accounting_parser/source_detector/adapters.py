"""Source-format adapters: per-vendor fingerprint rules.

Each adapter returns a confidence score in [0, 1] for a given document.
The Source_Detector combines signals multiplicatively across adapters
and classifies as the highest-scoring one above the Unknown threshold.

Fingerprint sources:
- PDF /Producer or /Creator metadata string
- XLSX sheet names, creator property, document structure
- IRS form PDFs use AcroForm field-name patterns
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from xml.etree import ElementTree as ET

from pypdf import PdfReader


# Confidence thresholds
UNKNOWN_THRESHOLD = 0.70
HIGH_CONFIDENCE_FLOOR = 0.85


@dataclass(frozen=True)
class DetectionSignal:
    source_system: str
    confidence: float
    signals: tuple[str, ...]  # human-readable reasons


class SourceFormatAdapter(Protocol):
    """Each adapter inspects a document and returns signals."""

    source_system: str

    def detect(self, path: Path) -> DetectionSignal | None:
        """Return a DetectionSignal if the document looks like this source,
        else None."""
        ...


# ---------- Helpers ----------


def _pdf_producer(path: Path) -> str:
    try:
        r = PdfReader(str(path))
        meta = r.metadata or {}
        parts: list[str] = []
        for key in ("/Producer", "/Creator", "/Author", "/Title", "/Subject"):
            v = meta.get(key, "")
            if v:
                parts.append(str(v))
        return " | ".join(parts).lower()
    except Exception:
        return ""


def _xlsx_creator_and_sheets(path: Path) -> tuple[str, tuple[str, ...]]:
    """Return (creator, sheet_names) for an XLSX, or ('', ()) on error."""
    try:
        with zipfile.ZipFile(path) as zf:
            core_xml = zf.read("docProps/core.xml").decode("utf-8", errors="replace")
            wb_xml = zf.read("xl/workbook.xml").decode("utf-8", errors="replace")
    except Exception:
        return "", ()
    creator = ""
    m = re.search(r"<dc:creator[^>]*>([^<]*)</dc:creator>", core_xml)
    if m:
        creator = m.group(1)
    sheets: list[str] = []
    for m in re.finditer(r'<sheet[^>]+name="([^"]+)"', wb_xml):
        sheets.append(m.group(1))
    return creator.lower(), tuple(sheets)


# ---------- Adapters ----------


class QuickBooksOnlineAdapter:
    source_system = "quickbooks_online"

    def detect(self, path: Path) -> DetectionSignal | None:
        prod = _pdf_producer(path)
        if "quickbooks online" in prod:
            return DetectionSignal(self.source_system, 0.95, (f"/Producer={prod}",))
        return None


class QuickBooksDesktopAdapter:
    source_system = "quickbooks_desktop"

    def detect(self, path: Path) -> DetectionSignal | None:
        prod = _pdf_producer(path)
        if "quickbooks desktop" in prod or "intuit" in prod and "desktop" in prod:
            return DetectionSignal(self.source_system, 0.90, (f"/Producer={prod}",))
        return None


class XeroAdapter:
    source_system = "xero"

    def detect(self, path: Path) -> DetectionSignal | None:
        if path.suffix.lower() != ".xlsx":
            return None
        creator, sheets = _xlsx_creator_and_sheets(path)
        if creator == "xero" or "Trial Balance" in sheets and creator == "xero":
            return DetectionSignal(self.source_system, 0.95, (f"creator={creator}",))
        if creator == "xero":
            return DetectionSignal(self.source_system, 0.90, (f"creator={creator}",))
        return None


class NetSuiteAdapter:
    source_system = "netsuite"

    def detect(self, path: Path) -> DetectionSignal | None:
        if path.suffix.lower() != ".xlsx":
            return None
        creator, sheets = _xlsx_creator_and_sheets(path)
        if creator == "netsuite":
            return DetectionSignal(self.source_system, 0.95, (f"creator={creator}",))
        return None


class SageIntacctAdapter:
    source_system = "sage_intacct"

    def detect(self, path: Path) -> DetectionSignal | None:
        prod = _pdf_producer(path)
        if "sage intacct" in prod:
            return DetectionSignal(self.source_system, 0.95, (f"/Producer={prod}",))
        return None


class CCHEngagementTemplateAdapter:
    source_system = "cch_engagement_template"

    # The template carries the canonical 13-column header row. We look for a
    # narrow fingerprint: the first row contains "Account Number" and
    # "Tax Grouping" columns.

    def detect(self, path: Path) -> DetectionSignal | None:
        if path.suffix.lower() != ".xlsx":
            return None
        try:
            with zipfile.ZipFile(path) as zf:
                # Shared strings table OR inline strings in the first sheet —
                # cheap way to find known header tokens.
                try:
                    ss = zf.read("xl/sharedStrings.xml").decode("utf-8", errors="replace")
                except KeyError:
                    ss = ""
                sheet1 = zf.read("xl/worksheets/sheet1.xml").decode("utf-8", errors="replace")
        except Exception:
            return None
        haystack = ss + sheet1
        tokens_required = ("Account Number", "Account Name", "Unadjusted", "Adjusted",
                           "Tax Basis", "Financial Statement Grouping", "Tax Grouping")
        hits = sum(1 for t in tokens_required if t in haystack)
        if hits >= 6:
            return DetectionSignal(
                self.source_system, 0.95,
                (f"13-column header tokens matched: {hits}/{len(tokens_required)}",),
            )
        if hits >= 4:
            return DetectionSignal(
                self.source_system, 0.75,
                (f"partial header tokens matched: {hits}/{len(tokens_required)}",),
            )
        return None


class IRSFormPDFAdapter:
    source_system = "irs_form_pdf"

    # IRS forms: title bar contains "Form <id>" and /Author often mentions IRS.
    _FORM_RE = re.compile(
        r"form\s+(w-?2|w-?9|1099[-\s]?(?:nec|misc|div|int)|1065|1120|1040|k-?1)",
        re.IGNORECASE,
    )

    def detect(self, path: Path) -> DetectionSignal | None:
        prod = _pdf_producer(path)
        try:
            r = PdfReader(str(path))
            if r.pages:
                page_text = (r.pages[0].extract_text() or "")[:4000]
            else:
                page_text = ""
        except Exception:
            page_text = ""
        signals: list[str] = []
        hits = 0
        if "irs" in prod or "internal revenue" in prod:
            hits += 1
            signals.append(f"producer: {prod}")
        # Check metadata AND page text for form id pattern
        haystack = prod + " " + page_text
        m = self._FORM_RE.search(haystack)
        if m:
            hits += 1
            signals.append(f"form match: {m.group(0)}")
        # IRS PDFs often have /Author = 'C:DC:TS:...' which is the IRS's
        # internal classification system
        if "c:dc:ts:" in prod:
            hits += 1
            signals.append("IRS internal author tag")
        if hits >= 2:
            return DetectionSignal(self.source_system, 0.95, tuple(signals))
        if hits == 1:
            return DetectionSignal(self.source_system, 0.80, tuple(signals))
        return None


class BankStatementPDFAdapter:
    source_system = "bank_statement_pdf"

    _BANKS = (
        "jpmorgan chase",
        "bank of america",
        "wells fargo",
        "u.s. bank",
        "us bank",
        "citibank",
    )

    def detect(self, path: Path) -> DetectionSignal | None:
        prod = _pdf_producer(path)
        try:
            r = PdfReader(str(path))
            text = ""
            for p in r.pages[:2]:
                text += (p.extract_text() or "")[:2000]
        except Exception:
            text = ""
        haystack = (prod + " " + text).lower()
        for b in self._BANKS:
            if b in haystack:
                return DetectionSignal(
                    self.source_system, 0.90, (f"bank={b}",)
                )
        if "statement period" in haystack and "account" in haystack:
            return DetectionSignal(
                self.source_system, 0.72, ("generic bank-statement phrasing",)
            )
        return None


class GenericFallbackAdapter:
    source_system = "generic"

    def detect(self, path: Path) -> DetectionSignal | None:
        return DetectionSignal(self.source_system, 0.50, ("fallback",))
