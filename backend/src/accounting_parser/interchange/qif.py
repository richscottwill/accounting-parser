"""QIF (Quicken Interchange Format) parser.

QIF is a simple line-oriented format:
    !Type:Bank
    Ddate
    Tamount
    Pdescription
    ^
    (next record)

Each field is prefixed by a single character code.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from accounting_parser.model.canonical import (
    Account,
    ParseResult,
    ReportLine,
    ReportSection,
    ReportType,
    SourceRef,
)


def parse_qif(
    qif_path: Path, *, document_id: UUID | None = None,
) -> ParseResult:
    doc_id = document_id or uuid4()
    text = qif_path.read_text(encoding="utf-8", errors="replace")
    lines_raw = text.splitlines()

    section_type: str | None = None
    current: dict[str, str] = {}
    records: list[dict[str, str]] = []

    for raw in lines_raw:
        if not raw:
            continue
        if raw.startswith("!Type:"):
            section_type = raw[len("!Type:"):].strip()
            continue
        if raw == "^":
            if current:
                records.append(current)
                current = {}
            continue
        code, value = raw[0], raw[1:]
        current[code] = value
    if current:
        records.append(current)

    out_lines: list[ReportLine] = []
    for i, rec in enumerate(records):
        amt = Decimal(rec.get("T", "0").replace(",", ""))
        desc = rec.get("P", "")
        debit = amt if amt > 0 else Decimal("0")
        credit = -amt if amt < 0 else Decimal("0")
        out_lines.append(ReportLine(
            line_id=f"qif-{i}",
            account=Account(
                account_number="qif-account",
                account_name=f"QIF {section_type or 'unknown'}",
            ),
            debit=debit,
            credit=credit,
            displayed_value=rec.get("T"),
            source_ref=SourceRef(document_id=doc_id),
        ))

    return ParseResult(
        document_id=doc_id,
        report_type=ReportType.BANK_STATEMENT,
        source_system="qif",
        parser_version="qif-0.1",
        parsed_at=datetime.now(timezone.utc),
        sections=(
            ReportSection(
                section_id=section_type or "unknown",
                title=f"QIF {section_type or 'unknown'}",
                lines=tuple(out_lines),
            ),
        ),
    )
