"""Bank statement PDF factory for top 5 US banks.

Produces a statement layout roughly matching each bank's real export:
header with bank logo text, account summary box, transaction table.
The parser exercises these in Task 8 (text extraction) and Task 11
(Azure Document Intelligence path).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Sequence

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
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


SUPPORTED_BANKS = ("Chase", "BoA", "Wells Fargo", "US Bank", "Citi")

BANK_METADATA = {
    "Chase": {"full_name": "JPMorgan Chase Bank, N.A.", "header_color": "#117ACA"},
    "BoA": {"full_name": "Bank of America, N.A.", "header_color": "#E31837"},
    "Wells Fargo": {"full_name": "Wells Fargo Bank, N.A.", "header_color": "#D71E28"},
    "US Bank": {"full_name": "U.S. Bank National Association", "header_color": "#0C2074"},
    "Citi": {"full_name": "Citibank, N.A.", "header_color": "#0077C8"},
}


@dataclass(frozen=True)
class Transaction:
    date: str       # MM/DD/YYYY
    description: str
    amount: Decimal  # positive = credit, negative = debit
    balance: Decimal


def _default_transactions(period_start: str = "12/01/2024") -> list[Transaction]:
    """Deterministic list of fake transactions for testing."""
    txs: list[Transaction] = []
    bal = Decimal("10000.00")
    entries = [
        ("12/01/2024", "Opening Balance", Decimal("0.00")),
        ("12/03/2024", "ACH DEPOSIT — PAYROLL", Decimal("4567.89")),
        ("12/05/2024", "POS PURCHASE — STAPLES", Decimal("-123.45")),
        ("12/08/2024", "WIRE TRANSFER OUT — VENDOR", Decimal("-2345.67")),
        ("12/10/2024", "CHECK #1234", Decimal("-500.00")),
        ("12/15/2024", "MONTHLY SERVICE FEE", Decimal("-15.00")),
        ("12/18/2024", "ACH DEPOSIT — CUSTOMER", Decimal("3456.78")),
        ("12/22/2024", "DEBIT CARD — OFFICE DEPOT", Decimal("-89.01")),
        ("12/28/2024", "INTEREST EARNED", Decimal("1.23")),
        ("12/31/2024", "ACH DEPOSIT — CUSTOMER", Decimal("2345.67")),
    ]
    for date, desc, amt in entries:
        bal += amt
        txs.append(Transaction(date=date, description=desc, amount=amt, balance=bal))
    return txs


def bank_statement_pdf_factory(
    bank: str,
    output_path: Path,
    *,
    account_number_masked: str = "****1234",
    period: tuple[str, str] = ("12/01/2024", "12/31/2024"),
    transactions: Sequence[Transaction] | None = None,
) -> Path:
    """Generate a synthetic bank statement PDF.

    Args:
        bank: One of ``SUPPORTED_BANKS``.
        output_path: Destination.
        account_number_masked: Last-4 masked account number.
        period: (start, end) date strings as MM/DD/YYYY.
        transactions: Override transaction list; default is a deterministic
            synthetic ledger.
    """
    if bank not in BANK_METADATA:
        raise ValueError(f"Unknown bank {bank!r}. Supported: {SUPPORTED_BANKS}")

    meta = BANK_METADATA[bank]
    txs = list(transactions) if transactions is not None else _default_transactions()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = BaseDocTemplate(
        str(output_path),
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=1.25 * inch,
        bottomMargin=0.75 * inch,
        title=f"{meta['full_name']} - Statement",
        author=meta["full_name"],
        creator=meta["full_name"],
        producer=f"{bank} Statement Generator",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height)

    def _header(canv, _doc):  # type: ignore[no-untyped-def]
        canv.setFillColor(colors.HexColor(meta["header_color"]))
        canv.rect(0, LETTER[1] - 0.9 * inch, LETTER[0], 0.9 * inch, fill=1, stroke=0)
        canv.setFillColor(colors.white)
        canv.setFont("Helvetica-Bold", 16)
        canv.drawString(0.75 * inch, LETTER[1] - 0.55 * inch, meta["full_name"])
        canv.setFont("Helvetica", 10)
        canv.drawString(0.75 * inch, LETTER[1] - 0.75 * inch, "Business Account Statement")

    doc.addPageTemplates(PageTemplate(id="bank", frames=frame, onPage=_header))

    styles = getSampleStyleSheet()

    summary_rows = [
        ["Account", f"Business Checking {account_number_masked}"],
        ["Statement Period", f"{period[0]} through {period[1]}"],
        ["Beginning Balance", f"${txs[0].balance - txs[0].amount:,.2f}"],
        ["Deposits & Credits", f"${sum((t.amount for t in txs if t.amount > 0), Decimal(0)):,.2f}"],
        ["Withdrawals & Debits", f"${sum((t.amount for t in txs if t.amount < 0), Decimal(0)):,.2f}"],
        ["Ending Balance", f"${txs[-1].balance:,.2f}"],
    ]
    summary = Table(summary_rows, colWidths=[2.0 * inch, 3.0 * inch])
    summary.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F0F0F0")),
                ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
            ]
        )
    )

    tx_rows: list[list[str]] = [["Date", "Description", "Amount", "Balance"]]
    for t in txs:
        amt = f"${t.amount:,.2f}" if t.amount >= 0 else f"(${-t.amount:,.2f})"
        tx_rows.append([t.date, t.description, amt, f"${t.balance:,.2f}"])

    tx_table = Table(
        tx_rows, colWidths=[0.9 * inch, 3.9 * inch, 1.1 * inch, 1.1 * inch], repeatRows=1
    )
    tx_table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E7E7E7")),
                ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
                ("ALIGN", (2, 0), (3, -1), "RIGHT"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )

    doc.build(
        [
            Paragraph("Account Summary", styles["Heading3"]),
            summary,
            Spacer(1, 0.2 * inch),
            Paragraph("Transaction Detail", styles["Heading3"]),
            tx_table,
        ]
    )
    return output_path
