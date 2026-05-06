"""OFX / QFX / QBO parser via ofxparse."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from ofxparse import OfxParser  # type: ignore[import-untyped]

from accounting_parser.model.canonical import (
    Account,
    ParseResult,
    ReportLine,
    ReportSection,
    ReportType,
    SourceRef,
)


def parse_ofx(
    ofx_path: Path, *, document_id: UUID | None = None,
) -> ParseResult:
    """Parse an OFX file into a Bank_Statement ParseResult.

    Produces one ReportLine per transaction with:
      - debit = amount if credit-side (deposit)
      - credit = |amount| if debit-side (withdrawal)
    Convention matches how a TB would book bank activity.
    """
    doc_id = document_id or uuid4()
    with ofx_path.open("rb") as f:
        ofx = OfxParser.parse(f)

    lines: list[ReportLine] = []
    for acct in ofx.accounts or []:
        stmt = acct.statement
        if stmt is None:
            continue
        for i, tx in enumerate(stmt.transactions or []):
            try:
                amt_raw = tx.amount  # type: ignore[attr-defined]
            except AttributeError:
                # InvestmentTransaction variants don't expose a single
                # amount attribute — at MVP we skip and defer detailed
                # investment handling to a follow-up task.
                continue
            if amt_raw is None:
                continue
            amt = Decimal(str(amt_raw))
            debit = amt if amt > 0 else Decimal("0")
            credit = -amt if amt < 0 else Decimal("0")
            line = ReportLine(
                line_id=f"tx-{i}",
                account=Account(
                    account_number=str(acct.account_id or acct.number or "unknown"),
                    account_name=f"Bank Account {acct.account_id or acct.number or ''}",
                ),
                debit=debit,
                credit=credit,
                balance=Decimal("0"),
                displayed_value=str(tx.amount),
                source_ref=SourceRef(document_id=doc_id),
            )
            lines.append(line)

    return ParseResult(
        document_id=doc_id,
        report_type=ReportType.BANK_STATEMENT,
        source_system="ofx",
        parser_version="ofx-0.1",
        parsed_at=datetime.now(timezone.utc),
        sections=(
            ReportSection(
                section_id="transactions",
                title="Transactions",
                lines=tuple(lines),
            ),
        ),
    )
