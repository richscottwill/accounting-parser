"""QuickBooks Online Trial Balance PDF factory.

Produces a PDF that mimics the QuickBooks Online TB export layout:
two-column Debit / Credit, account-number prefix, company header, period,
"TOTAL" row at the bottom. Metadata sets /Producer to "QuickBooks Online
Reporting" so Source_Detector fingerprinting works.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Sequence

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from factories._data import DEFAULT_CHART, Account, balanced_debits_credits


def _fmt_money(v: Decimal) -> str:
    return f"{v:,.2f}"


def qbo_tb_pdf_factory(
    output_path: Path,
    *,
    company_name: str = "Synthetic Demo Co, LLC",
    period_end: str = "December 31, 2024",
    accounts: Sequence[Account] | None = None,
    multi_page: bool = True,
) -> Path:
    """Generate a QuickBooks Online Trial Balance PDF.

    Args:
        output_path: Where to write the PDF.
        company_name: Fake company name. Must be obviously-not-real.
        period_end: End-of-period date string.
        accounts: Account chart; defaults to ``DEFAULT_CHART``.
        multi_page: If True, pad with duplicated accounts so the TB spans
            multiple pages (exercises page-break stitching).

    Returns:
        ``output_path`` for chaining.
    """
    accs = tuple(accounts) if accounts is not None else DEFAULT_CHART
    if multi_page:
        # Pad to ~45 rows so the table wraps to a second page.
        pad: list[Account] = []
        for i in range(25):
            base = accs[i % len(accs)]
            pad.append(
                Account(
                    number=f"9{i:03d}",
                    name=f"Fake Padding Account {i:02d}",
                    type=base.type,
                    normal_balance=base.normal_balance,
                    balance=Decimal("100.00") + Decimal(i),
                )
            )
        accs = accs + tuple(pad)

    debits, credits = balanced_debits_credits(accs)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = BaseDocTemplate(
        str(output_path),
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title=f"Trial Balance - {company_name}",
        author="QuickBooks Online",
        creator="QuickBooks Online",
        producer="QuickBooks Online Reporting",
    )
    frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        doc.width,
        doc.height,
        showBoundary=0,
    )

    def _draw_header(canv: canvas.Canvas, _doc: BaseDocTemplate) -> None:
        canv.setFont("Helvetica-Bold", 14)
        canv.drawCentredString(LETTER[0] / 2, LETTER[1] - 0.5 * inch, company_name)
        canv.setFont("Helvetica-Bold", 12)
        canv.drawCentredString(LETTER[0] / 2, LETTER[1] - 0.7 * inch, "TRIAL BALANCE")
        canv.setFont("Helvetica", 10)
        canv.drawCentredString(
            LETTER[0] / 2, LETTER[1] - 0.88 * inch, f"As of {period_end}"
        )

    doc.addPageTemplates(PageTemplate(id="qbo", frames=frame, onPage=_draw_header))

    styles = getSampleStyleSheet()
    tiny = ParagraphStyle("tiny", parent=styles["Normal"], fontSize=8)

    rows: list[list[str]] = [["Account", "Account Name", "Debit", "Credit"]]
    for a in accs:
        dr = _fmt_money(a.balance) if a.normal_balance == "debit" else ""
        cr = _fmt_money(a.balance) if a.normal_balance == "credit" else ""
        rows.append([a.number, a.name, dr, cr])
    rows.append(["", "TOTAL", _fmt_money(debits), _fmt_money(credits)])

    table = Table(
        rows,
        colWidths=[0.9 * inch, 3.6 * inch, 1.4 * inch, 1.4 * inch],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
                ("LINEABOVE", (0, -1), (-1, -1), 0.75, colors.black),
                ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 9),
                ("FONT", (0, 1), (-1, -2), "Helvetica", 9),
                ("ALIGN", (2, 0), (3, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )

    doc.build(
        [
            Spacer(1, 0.5 * inch),
            Paragraph(f"Prepared {period_end}. Values in USD.", tiny),
            Spacer(1, 0.1 * inch),
            table,
        ]
    )
    return output_path
