"""QuickBooks Desktop General Ledger PDF factory (landscape two-column).

Mimics the QuickBooks Desktop GL export: landscape orientation, per-account
transaction list with Date / Num / Name / Memo / Split / Debit / Credit /
Balance columns. /Producer metadata set to "QuickBooks Desktop".
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Sequence

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.lib.units import inch
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

from factories._data import DEFAULT_CHART, Account


def _fmt_money(v: Decimal) -> str:
    return f"{v:,.2f}"


def _gl_transactions(account: Account, n: int = 4) -> list[list[str]]:
    """Generate fake transactions for one account. Deterministic."""
    rows: list[list[str]] = []
    running = Decimal("0.00")
    for i in range(n):
        amount = (account.balance / Decimal(n)).quantize(Decimal("0.01"))
        running += amount
        date = f"12/{(i * 7) + 1:02d}/2024"
        num = f"TX{account.number}{i:02d}"
        memo = f"Sample transaction {i+1} for {account.name[:30]}"
        if account.normal_balance == "debit":
            rows.append([date, num, "Demo Vendor", memo, "Split", _fmt_money(amount), "", _fmt_money(running)])
        else:
            rows.append([date, num, "Demo Customer", memo, "Split", "", _fmt_money(amount), _fmt_money(running)])
    return rows


def qbd_gl_pdf_factory(
    output_path: Path,
    *,
    company_name: str = "Synthetic Demo Co, LLC",
    period_end: str = "December 31, 2024",
    accounts: Sequence[Account] | None = None,
) -> Path:
    """Generate a QuickBooks Desktop General Ledger PDF (landscape)."""
    accs = tuple(accounts) if accounts is not None else DEFAULT_CHART[:8]

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    page_size = landscape(LETTER)
    doc = BaseDocTemplate(
        str(output_path),
        pagesize=page_size,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.5 * inch,
        title=f"General Ledger - {company_name}",
        author="Intuit",
        creator="QuickBooks Desktop",
        producer="QuickBooks Desktop",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height)

    def _header(canv, _doc):  # type: ignore[no-untyped-def]
        canv.setFont("Helvetica-Bold", 12)
        canv.drawCentredString(page_size[0] / 2, page_size[1] - 0.3 * inch, company_name)
        canv.setFont("Helvetica-Bold", 10)
        canv.drawCentredString(page_size[0] / 2, page_size[1] - 0.48 * inch, "General Ledger")
        canv.setFont("Helvetica", 8)
        canv.drawCentredString(
            page_size[0] / 2, page_size[1] - 0.6 * inch, f"All Transactions through {period_end}"
        )

    doc.addPageTemplates(PageTemplate(id="qbd", frames=frame, onPage=_header))

    styles = getSampleStyleSheet()
    story: list = []

    for acc in accs:
        story.append(Paragraph(f"<b>{acc.number} · {acc.name}</b>", styles["Normal"]))
        header = ["Date", "Num", "Name", "Memo", "Split", "Debit", "Credit", "Balance"]
        rows = [header] + _gl_transactions(acc)
        table = Table(
            rows,
            colWidths=[0.8 * inch, 0.8 * inch, 1.4 * inch, 2.6 * inch, 0.8 * inch, 1.0 * inch, 1.0 * inch, 1.1 * inch],
            repeatRows=1,
        )
        table.setStyle(
            TableStyle(
                [
                    ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("FONT", (0, 1), (-1, -1), "Helvetica", 8),
                    ("ALIGN", (5, 0), (7, -1), "RIGHT"),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.25, colors.black),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 0.12 * inch))

    doc.build(story)
    return output_path
