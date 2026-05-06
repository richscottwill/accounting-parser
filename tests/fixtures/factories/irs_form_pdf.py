"""IRS form PDF factory (synthetic approximations).

Generates printable facsimiles of W-2, 1099-NEC, 1099-MISC, 1099-DIV,
1099-INT, K-1 (1065), K-1 (1120S). The real IRS forms are public domain,
but faithful rendering requires the official AcroForm templates. Our
factory produces a layout that a parser can locate the key boxes in
(box number + label + value) using text-native pdfplumber extraction —
which is what Tasks 8-9 actually test.

Supported form_ids: "W-2", "1099-NEC", "1099-MISC", "1099-DIV", "1099-INT",
"K-1-1065", "K-1-1120S".

Fields are dicts of {box_id: value}. Any keys not recognized by the form
layout are rendered in an "Additional notes" section to avoid silent loss.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


# Minimal field layouts: (box_id, label, x, y, width)
# Positions are in inches from bottom-left. Approximate — good enough for
# text-native parsing tests where the parser uses label proximity rather
# than absolute coordinates.
FORM_LAYOUTS: dict[str, tuple[str, list[tuple[str, str, float, float, float]]]] = {
    "W-2": (
        "Form W-2 Wage and Tax Statement (synthetic)",
        [
            ("a", "Employee SSN (synthetic)", 5.0, 9.7, 2.5),
            ("b", "Employer ID Number (EIN)", 0.8, 9.0, 2.5),
            ("c", "Employer name & address", 0.8, 8.2, 3.5),
            ("e", "Employee name", 0.8, 7.4, 3.5),
            ("1", "Wages, tips, other compensation", 5.0, 9.0, 2.5),
            ("2", "Federal income tax withheld", 5.0, 8.4, 2.5),
            ("3", "Social security wages", 5.0, 7.8, 2.5),
            ("4", "Social security tax withheld", 5.0, 7.2, 2.5),
            ("5", "Medicare wages & tips", 5.0, 6.6, 2.5),
            ("6", "Medicare tax withheld", 5.0, 6.0, 2.5),
            ("15", "State", 0.8, 4.5, 1.0),
            ("16", "State wages, tips, etc.", 2.0, 4.5, 2.5),
            ("17", "State income tax", 5.0, 4.5, 2.5),
        ],
    ),
    "1099-NEC": (
        "Form 1099-NEC Nonemployee Compensation (synthetic)",
        [
            ("payer", "PAYER name & address", 0.8, 9.3, 3.5),
            ("payer-tin", "PAYER TIN", 0.8, 8.3, 2.5),
            ("recipient", "RECIPIENT name & address", 0.8, 7.4, 3.5),
            ("recipient-tin", "RECIPIENT TIN", 0.8, 6.5, 2.5),
            ("1", "Nonemployee compensation", 5.0, 8.3, 2.5),
            ("4", "Federal income tax withheld", 5.0, 7.4, 2.5),
            ("5", "State tax withheld", 5.0, 5.5, 2.5),
            ("6", "State/Payer's state no.", 5.0, 4.9, 2.5),
            ("7", "State income", 5.0, 4.3, 2.5),
        ],
    ),
    "1099-MISC": (
        "Form 1099-MISC Miscellaneous Information (synthetic)",
        [
            ("payer", "PAYER name & address", 0.8, 9.3, 3.5),
            ("payer-tin", "PAYER TIN", 0.8, 8.3, 2.5),
            ("recipient", "RECIPIENT name & address", 0.8, 7.4, 3.5),
            ("recipient-tin", "RECIPIENT TIN", 0.8, 6.5, 2.5),
            ("1", "Rents", 5.0, 9.0, 2.5),
            ("2", "Royalties", 5.0, 8.3, 2.5),
            ("3", "Other income", 5.0, 7.7, 2.5),
            ("4", "Federal income tax withheld", 5.0, 7.1, 2.5),
        ],
    ),
    "1099-DIV": (
        "Form 1099-DIV Dividends and Distributions (synthetic)",
        [
            ("payer", "PAYER name & address", 0.8, 9.3, 3.5),
            ("recipient", "RECIPIENT name & address", 0.8, 7.4, 3.5),
            ("1a", "Total ordinary dividends", 5.0, 9.0, 2.5),
            ("1b", "Qualified dividends", 5.0, 8.3, 2.5),
            ("2a", "Total capital gain distr.", 5.0, 7.7, 2.5),
            ("4", "Federal income tax withheld", 5.0, 6.5, 2.5),
        ],
    ),
    "1099-INT": (
        "Form 1099-INT Interest Income (synthetic)",
        [
            ("payer", "PAYER name & address", 0.8, 9.3, 3.5),
            ("recipient", "RECIPIENT name & address", 0.8, 7.4, 3.5),
            ("1", "Interest income", 5.0, 9.0, 2.5),
            ("2", "Early withdrawal penalty", 5.0, 8.3, 2.5),
            ("3", "Interest on U.S. Savings Bonds", 5.0, 7.7, 2.5),
            ("4", "Federal income tax withheld", 5.0, 6.5, 2.5),
        ],
    ),
    "K-1-1065": (
        "Schedule K-1 (Form 1065) Partner's Share (synthetic)",
        [
            ("part-i-a", "Partnership EIN", 0.8, 9.0, 2.5),
            ("part-i-b", "Partnership name & address", 0.8, 8.2, 3.5),
            ("part-ii-e", "Partner SSN/TIN", 0.8, 7.0, 2.5),
            ("part-ii-f", "Partner name & address", 0.8, 6.2, 3.5),
            ("1", "Ordinary business income (loss)", 5.0, 8.0, 2.5),
            ("2", "Net rental real estate income", 5.0, 7.4, 2.5),
            ("5", "Interest income", 5.0, 6.2, 2.5),
            ("6a", "Ordinary dividends", 5.0, 5.6, 2.5),
            ("14", "Self-employment earnings", 5.0, 4.4, 2.5),
        ],
    ),
    "K-1-1120S": (
        "Schedule K-1 (Form 1120-S) Shareholder's Share (synthetic)",
        [
            ("part-i-a", "Corp EIN", 0.8, 9.0, 2.5),
            ("part-i-b", "Corp name & address", 0.8, 8.2, 3.5),
            ("part-ii-d", "Shareholder SSN/TIN", 0.8, 7.0, 2.5),
            ("part-ii-e", "Shareholder name", 0.8, 6.2, 3.5),
            ("1", "Ordinary business income (loss)", 5.0, 8.0, 2.5),
            ("5a", "Ordinary dividends", 5.0, 6.2, 2.5),
            ("7", "Net short-term capital gain", 5.0, 5.0, 2.5),
            ("17-AC", "Section 199A info (QBI)", 5.0, 3.8, 2.5),
        ],
    ),
}


def irs_form_pdf_factory(
    form_id: str,
    output_path: Path,
    *,
    fields: Mapping[str, str] | None = None,
) -> Path:
    """Generate a synthetic IRS form PDF.

    Args:
        form_id: One of the keys in ``FORM_LAYOUTS``.
        output_path: Where to write the PDF.
        fields: Mapping of box_id -> value string. Unknown keys render in
            a notes section.

    Raises:
        ValueError: if ``form_id`` is not recognized.
    """
    if form_id not in FORM_LAYOUTS:
        raise ValueError(
            f"Unknown form_id {form_id!r}. Supported: {sorted(FORM_LAYOUTS)}"
        )

    title, layout = FORM_LAYOUTS[form_id]
    fields = dict(fields or {})

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    c = canvas.Canvas(str(output_path), pagesize=LETTER)
    c.setTitle(title)
    c.setAuthor("Internal Revenue Service (synthetic)")
    c.setCreator("accounting-parser fixture factory")
    c.setSubject(f"Synthetic {form_id}")

    # Title bar
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(LETTER[0] / 2, LETTER[1] - 0.5 * inch, title)
    c.setFont("Helvetica-Oblique", 8)
    c.drawCentredString(
        LETTER[0] / 2,
        LETTER[1] - 0.7 * inch,
        "SYNTHETIC DATA — NOT A REAL TAX FORM — DO NOT FILE",
    )

    # Draw labeled boxes
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.5)
    known_keys = set()
    for box_id, label, x, y, w in layout:
        known_keys.add(box_id)
        value = fields.get(box_id, "")
        # Box
        c.rect(x * inch, y * inch, w * inch, 0.5 * inch, stroke=1, fill=0)
        # Box id
        c.setFont("Helvetica-Bold", 7)
        c.drawString(x * inch + 2, y * inch + 0.38 * inch, f"Box {box_id}")
        # Label
        c.setFont("Helvetica", 7)
        c.drawString(x * inch + 32, y * inch + 0.38 * inch, label)
        # Value
        c.setFont("Helvetica", 10)
        c.drawString(x * inch + 4, y * inch + 0.12 * inch, str(value))

    # Unknown fields section
    extras = {k: v for k, v in fields.items() if k not in known_keys}
    if extras:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(0.8 * inch, 2.5 * inch, "Additional notes (not on standard layout)")
        c.setFont("Helvetica", 8)
        y = 2.25 * inch
        for k, v in extras.items():
            c.drawString(0.8 * inch, y, f"  {k}: {v}")
            y -= 0.18 * inch

    c.showPage()
    c.save()
    return output_path
