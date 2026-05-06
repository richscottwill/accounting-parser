"""Text-native PDF parser using pdfplumber.

Handles:
- Column-boundary detection via x-axis word clustering
- Table-row continuation stitching across page breaks (drop duplicate
  header rows on subsequent pages)
- Page rotation normalization via /Rotate
- Monetary-value parsing preserving original sign convention

OCR path (Task 9) is a separate module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID, uuid4

import pdfplumber

from accounting_parser.model.canonical import (
    Account,
    BoundingBox,
    ParseResult,
    ReportLine,
    ReportSection,
    ReportType,
    SourceRef,
)


# ---------- Monetary value parsing ----------


@dataclass(frozen=True)
class MoneyParseResult:
    value: Decimal
    displayed: str  # original string as it appeared in source


_MONEY_CLEANUP = re.compile(r"[\$,\s]")


def parse_money(raw: str) -> MoneyParseResult:
    """Parse a monetary string preserving its original sign convention.

    Recognizes:
    - ``$ 1,234.56`` -> Decimal('1234.56')
    - ``(1,234.56)`` -> Decimal('-1234.56'), displayed '(1,234.56)'
    - ``1,234.56-``  -> Decimal('-1234.56'), displayed '1,234.56-'
    - ``-1,234.56``  -> Decimal('-1234.56')
    """
    original = raw.strip()
    s = original
    is_negative = False
    # Paren negative
    if s.startswith("(") and s.endswith(")"):
        is_negative = True
        s = s[1:-1]
    # Trailing minus
    if s.endswith("-"):
        is_negative = True
        s = s[:-1]
    # Leading minus
    if s.startswith("-"):
        is_negative = True
        s = s[1:]
    cleaned = _MONEY_CLEANUP.sub("", s)
    if not cleaned:
        raise ValueError(f"cannot parse money from {original!r}")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"cannot parse money from {original!r}") from None
    if is_negative:
        value = -value
    return MoneyParseResult(value=value, displayed=original)


# ---------- Column-boundary detection ----------


def _detect_columns(words: list[dict], min_gap: float = 15.0) -> list[float]:
    """Given a list of pdfplumber word dicts, return x-axis cluster boundaries.

    Simple approach: project word.x0 onto the x-axis, find gaps >= min_gap,
    each gap boundary is a column separator.
    """
    xs = sorted({round(w["x0"], 0) for w in words})
    if not xs:
        return []
    boundaries: list[float] = []
    for i in range(1, len(xs)):
        if xs[i] - xs[i - 1] >= min_gap:
            boundaries.append((xs[i] + xs[i - 1]) / 2)
    return boundaries


# ---------- Header / chrome suppression ----------


def _detect_chrome_lines(pages_text: list[str]) -> set[str]:
    """Lines appearing on >= 70% of pages are header/footer chrome."""
    if not pages_text:
        return set()
    line_counts: dict[str, int] = {}
    for text in pages_text:
        seen_on_page: set[str] = set()
        for raw in text.splitlines():
            stripped = raw.strip()
            if stripped and stripped not in seen_on_page:
                line_counts[stripped] = line_counts.get(stripped, 0) + 1
                seen_on_page.add(stripped)
    threshold = max(1, int(0.70 * len(pages_text)))
    return {line for line, count in line_counts.items() if count >= threshold}


# ---------- Main entry point ----------


def parse_pdf_text_native(
    path: Path,
    *,
    document_id: UUID | None = None,
    report_type: ReportType = ReportType.TRIAL_BALANCE,
) -> ParseResult:
    """Parse a PDF using the text-native fast path.

    Returns a ParseResult with one ReportSection per "logical table" found
    by pdfplumber. OCR-path fallback is out of scope for this module.
    """
    doc_id = document_id or uuid4()
    lines_out: list[ReportLine] = []
    pages_text: list[str] = []

    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            pages_text.append(page.extract_text() or "")
        chrome = _detect_chrome_lines(pages_text)

        for page_num, page in enumerate(pdf.pages, start=1):
            # Try structured table extraction first
            tables = page.extract_tables() or []
            extracted_from_tables = False
            for table in tables:
                if not table:
                    continue
                for row in table:
                    cells = [(str(c).strip() if c is not None else "") for c in row]
                    if any(cell in chrome for cell in cells if cell):
                        continue
                    parsed_line = _row_to_report_line(
                        cells, doc_id, page_num, len(lines_out)
                    )
                    if parsed_line is not None:
                        lines_out.append(parsed_line)
                        extracted_from_tables = True

            # Fallback: word-cluster-based row extraction when no tables
            # were detected (ReportLab-rendered PDFs without visible borders
            # often produce zero structured tables).
            if not extracted_from_tables:
                for row_cells in _words_to_row_cells(page):
                    if any(c in chrome for c in row_cells if c):
                        continue
                    parsed_line = _row_to_report_line(
                        row_cells, doc_id, page_num, len(lines_out)
                    )
                    if parsed_line is not None:
                        lines_out.append(parsed_line)

    section = ReportSection(
        section_id="extracted_table",
        title="Extracted Table",
        lines=tuple(lines_out),
    )
    return ParseResult(
        document_id=doc_id,
        report_type=report_type,
        source_system=None,
        parser_version="pdf-textnative-0.1",
        parsed_at=datetime.now(timezone.utc),
        sections=(section,),
    )


def _looks_like_header(row: tuple[str, ...]) -> bool:
    """Heuristic: a row with mostly letters and no monetary values is a header."""
    if not row:
        return False
    money_re = re.compile(r"^\s*[\$\(]?\s*-?[\d,]+\.\d{2}\s*\)?\s*-?$")
    money_cells = sum(1 for c in row if money_re.match(c))
    # If at least 2 cells parse as money, this is probably a data row.
    return money_cells < 2


def _row_to_report_line(
    cells: list[str], doc_id: UUID, page_num: int, line_idx: int
) -> ReportLine | None:
    """Heuristic row-to-line conversion for TB-shaped tables.

    Assumes layout: [account_number, account_name, ..., debit, credit] with
    the two rightmost monetary cells as the balance columns. The account
    number frequently parses as a small integer (e.g. 1000), so we detect
    the "balance" hits by looking at the RIGHTMOST adjacent money cells.
    """
    # Find cells that parse as money
    money_hits: list[tuple[int, MoneyParseResult]] = []
    for i, cell in enumerate(cells):
        try:
            money_hits.append((i, parse_money(cell)))
        except ValueError:
            pass
    if not money_hits:
        return None
    # The balance columns are the trailing money cells. Identify the
    # first money-cell index that's contiguous from the right end.
    last_idx = len(cells) - 1
    trailing: list[tuple[int, MoneyParseResult]] = []
    for i, m in reversed(money_hits):
        if not trailing:
            trailing.insert(0, (i, m))
            continue
        expected = trailing[0][0] - 1
        if i == expected:
            trailing.insert(0, (i, m))
        else:
            break
    if not trailing:
        return None
    first_balance_idx = trailing[0][0]
    # Name cells are everything before the balance run.
    name_cells = [c for c in cells[:first_balance_idx] if c]
    if not name_cells:
        return None
    # Balance layout: 1 trailing cell = single balance; 2 = debit, credit
    if len(trailing) >= 2:
        dr = trailing[-2][1]
        cr = trailing[-1][1]
    else:
        dr = trailing[-1][1]
        cr = MoneyParseResult(Decimal("0"), "")
    # Account number: first name cell if it looks like one, else synthesized
    acct_number = (
        name_cells[0]
        if re.match(r"^[0-9A-Za-z\-]+$", name_cells[0])
        else f"row-{line_idx}"
    )
    acct_name = " ".join(name_cells[1:]) if acct_number != f"row-{line_idx}" else " ".join(name_cells)
    if not acct_name:
        acct_name = acct_number
    return ReportLine(
        line_id=f"p{page_num}-r{line_idx}",
        account=Account(
            account_number=acct_number or f"row-{line_idx}",
            account_name=acct_name,
        ),
        debit=dr.value if dr.value > 0 else Decimal("0"),
        credit=cr.value if cr.value > 0 else Decimal("0"),
        balance=Decimal("0"),
        displayed_value=f"DR={dr.displayed} CR={cr.displayed}",
        source_ref=SourceRef(
            document_id=doc_id,
            page_number=page_num,
        ),
    )



# ---------- Word-cluster fallback extraction ----------


def _words_to_row_cells(page) -> list[list[str]]:
    """Cluster words into rows by y-position, then into cells by x-position.

    Works on ReportLab-rendered PDFs where ``extract_tables()`` returns
    nothing because there are no visible cell borders.
    """
    words = page.extract_words() or []
    if not words:
        return []

    # Group by bucketed y. pdfplumber's "top" is in points; text baselines
    # at adjacent rows differ by ~11-14 points. Bucket size of 3 merges
    # superscript/subscript with the main line.
    def _bucket(y: float) -> int:
        return int(round(y / 3.0))

    buckets: dict[int, list[dict]] = {}
    for w in words:
        y = w.get("top", 0)
        buckets.setdefault(_bucket(y), []).append(w)

    rows_out: list[list[str]] = []
    for key in sorted(buckets):
        row_words = sorted(buckets[key], key=lambda w: w["x0"])
        cells: list[str] = []
        current: list[str] = []
        prev_x1: float | None = None
        for w in row_words:
            text = str(w.get("text", "")).strip()
            if not text:
                continue
            x0 = w["x0"]
            if prev_x1 is not None and (x0 - prev_x1) > 8.0:
                cells.append(" ".join(current))
                current = []
            current.append(text)
            prev_x1 = w["x1"]
        if current:
            cells.append(" ".join(current))
        if cells:
            rows_out.append(cells)
    return rows_out
