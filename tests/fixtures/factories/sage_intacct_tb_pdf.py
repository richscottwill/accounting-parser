"""Sage Intacct Trial Balance PDF factory (simpler single-column layout)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Sequence

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
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
from reportlab.lib.styles import getSampleStyleSheet

from factories._data import DEFAULT_CHART, Account, balanced_debits_credits


def _fmt_money(v: Decimal) -> str:
    return f"{v:,.2f}"


def sage_intacct_tb_pdf_factory(
    output_path: Path,
    *,
    company_name: str = "Synthetic Demo Co, LLC",
    period_end: str = "December 31, 2024",
    accounts: Sequence[Account] | None = None,
) -> Path:
    """Generate a Sage Intacct Trial Balance PDF."""
    accs = tuple(accounts) if accounts is not None else DEFAULT_CHART
    debits, credits = balanced_debits_credits(accs)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = BaseDocTemplate(
        str(output_path),
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.85 * inch,
        bottomMargin=0.75 * inch,
        title=f"Trial Balance - {company_name}",
        author="Sage Intacct",
        creator="Sage Intacct Reporting",
        producer="Sage Intacct",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height)

    def _header(canv: canvas.Canvas, _doc: BaseDocTemplate) -> None:
        canv.setFont("Helvetica-Bold", 13)
        canv.drawString(doc.leftMargin, LETTER[1] - 0.5 * inch, company_name)
        canv.setFont("Helvetica", 9)
        canv.drawString(doc.leftMargin, LETTER[1] - 0.68 * inch, f"Trial Balance — as of {period_end}")
        canv.drawRightString(
            LETTER[0] - doc.rightMargin, LETTER[1] - 0.68 * inch, "Reported in USD"
        )

    doc.addPageTemplates(PageTemplate(id="intacct", frames=frame, onPage=_header))

    styles = getSampleStyleSheet()
    rows: list[list[str]] = [["Account Code", "Account Name", "Type", "Debit", "Credit"]]
    for a in accs:
        dr = _fmt_money(a.balance) if a.normal_balance == "debit" else ""
        cr = _fmt_money(a.balance) if a.normal_balance == "credit" else ""
        rows.append([a.number, a.name, a.type, dr, cr])
    rows.append(["", "Grand Total", "", _fmt_money(debits), _fmt_money(credits)])

    table = Table(
        rows,
        colWidths=[1.0 * inch, 3.0 * inch, 1.0 * inch, 1.1 * inch, 1.1 * inch],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
                ("ALIGN", (3, 0), (4, -1), "RIGHT"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
                ("LINEABOVE", (0, -1), (-1, -1), 0.75, colors.black),
                ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 9),
            ]
        )
    )

    doc.build(
        [
            Spacer(1, 0.15 * inch),
            Paragraph("Generated report — all values shown as of period end.", styles["Italic"]),
            Spacer(1, 0.1 * inch),
            table,
        ]
    )
    return output_path
