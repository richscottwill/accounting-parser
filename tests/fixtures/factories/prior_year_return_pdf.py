"""Prior-year return PDF factory (1120-S synthetic facsimile).

Used by Task 19 (carryforward rollforward) and Task 22 (prior-year pdf
parsing). A minimal 1120-S-shaped PDF with the key data-entry boxes
populated so the parser can locate carryforwards.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


def prior_year_1120s_factory(
    output_path: Path,
    *,
    tax_year: int = 2023,
    entity_name: str = "Synthetic Demo Co, LLC",
    ein: str = "00-0000000",
) -> Path:
    """Generate a synthetic Form 1120-S prior-year return PDF."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    c = canvas.Canvas(str(output_path), pagesize=LETTER)
    c.setTitle(f"Form 1120-S Tax Year {tax_year} (synthetic)")
    c.setAuthor("accounting-parser fixture factory")
    c.setCreator("accounting-parser")

    # Header
    c.setFont("Helvetica-Bold", 14)
    c.drawString(0.8 * inch, 10.3 * inch, f"Form 1120-S — Tax Year {tax_year}")
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(
        0.8 * inch, 10.1 * inch,
        "SYNTHETIC DATA — NOT A REAL TAX RETURN — DO NOT FILE",
    )
    c.setFont("Helvetica", 10)
    c.drawString(0.8 * inch, 9.8 * inch, f"Entity: {entity_name}")
    c.drawString(0.8 * inch, 9.6 * inch, f"EIN: {ein}")

    # Key data lines the parser needs to locate
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.8 * inch, 9.2 * inch, "Page 1 — Income / Deductions")
    c.setFont("Helvetica", 10)
    lines = [
        ("Line 1a", "Gross receipts or sales", "1,469,135.78"),
        ("Line 2",  "Cost of goods sold",     "567,890.12"),
        ("Line 6",  "Total income",           "901,245.66"),
        ("Line 20", "Total deductions",       "789,012.34"),
        ("Line 21", "Ordinary business income (loss)", "112,233.32"),
    ]
    y = 8.95 * inch
    for num, label, value in lines:
        c.drawString(0.8 * inch, y, num)
        c.drawString(1.6 * inch, y, label)
        c.drawRightString(7.5 * inch, y, value)
        y -= 0.22 * inch

    # Schedule K — carryforwards
    y -= 0.3 * inch
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.8 * inch, y, "Schedule K — Shareholders' Pro Rata Share Items")
    y -= 0.25 * inch
    c.setFont("Helvetica", 10)
    k_lines = [
        ("Line 1",    "Ordinary business income (loss)",         "112,233.32"),
        ("Line 5a",   "Ordinary dividends",                       "  3,456.78"),
        ("Line 12",   "Section 179 expense deduction",           " 12,500.00"),
        ("Line 16C",  "Nondeductible expenses",                   "  1,234.56"),
        ("Line 17AC", "Section 199A (QBI) information",           "112,233.32"),
    ]
    for num, label, value in k_lines:
        c.drawString(0.8 * inch, y, num)
        c.drawString(1.6 * inch, y, label)
        c.drawRightString(7.5 * inch, y, value)
        y -= 0.22 * inch

    # Schedule L — Balance Sheet ending balances
    y -= 0.3 * inch
    c.setFont("Helvetica-Bold", 10)
    c.drawString(0.8 * inch, y, "Schedule L — Balance Sheet per Books (end of year)")
    y -= 0.25 * inch
    c.setFont("Helvetica", 10)
    l_lines = [
        ("Line 1",   "Cash",                         "146,913.56"),
        ("Line 2a",  "Trade notes/accounts receivable", "234,567.89"),
        ("Line 10a", "Buildings and other depreciable assets", "567,890.12"),
        ("Line 10b", "Less accumulated depreciation", "(123,456.78)"),
        ("Line 25",  "Retained earnings — Schedule M-2", "456,789.01"),
    ]
    for num, label, value in l_lines:
        c.drawString(0.8 * inch, y, num)
        c.drawString(1.6 * inch, y, label)
        c.drawRightString(7.5 * inch, y, value)
        y -= 0.22 * inch

    c.setStrokeColor(colors.grey)
    c.setLineWidth(0.25)
    c.line(0.8 * inch, 0.6 * inch, LETTER[0] - 0.8 * inch, 0.6 * inch)
    c.setFont("Helvetica-Oblique", 7)
    c.drawCentredString(
        LETTER[0] / 2, 0.45 * inch,
        f"Synthetic Form 1120-S for tax year {tax_year}. "
        "All data is fictional. Used solely for accounting-parser test fixtures.",
    )

    c.showPage()
    c.save()
    return output_path
