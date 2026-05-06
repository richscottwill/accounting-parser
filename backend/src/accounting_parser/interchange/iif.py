"""QuickBooks IIF parser.

IIF is a tab-separated format with header rows prefixed by ``!`` and
data rows matching the most recent header by first-column tag.

    !ACCNT\tNAME\tACCNTTYPE
    ACCNT\tCash\tASSET
    !TRNS\tTRNSID\tTRNSTYPE\tDATE\tACCNT\tAMOUNT\tNAME\tMEMO
    TRNS\t...

Required columns per header type are enforced — missing ones produce a
structured validator finding.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from accounting_parser.model.canonical import (
    Account,
    AccountType,
    ParseResult,
    ReportLine,
    ReportSection,
    ReportType,
    SourceRef,
)


IIF_GRAMMAR_ERROR = "R6.1.iif_grammar"


# Required columns per IIF header tag. Kept minimal; real IIF has more
# per-tag variation.
REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "ACCNT": ("NAME", "ACCNTTYPE"),
    "TRNS": ("DATE", "ACCNT", "AMOUNT"),
    "SPL": ("ACCNT", "AMOUNT"),
}


@dataclass(frozen=True)
class IIFGrammarFinding:
    rule_id: str
    severity: str
    message: str


def parse_iif(
    iif_path: Path, *, document_id: UUID | None = None,
) -> tuple[ParseResult, list[IIFGrammarFinding]]:
    doc_id = document_id or uuid4()
    findings: list[IIFGrammarFinding] = []

    text = iif_path.read_text(encoding="utf-8", errors="replace")
    headers: dict[str, list[str]] = {}
    accounts: list[Account] = []
    lines_out: list[ReportLine] = []

    for lineno, raw in enumerate(text.splitlines(), start=1):
        if not raw:
            continue
        cells = raw.split("\t")
        if cells[0].startswith("!"):
            tag = cells[0][1:]
            headers[tag] = cells[1:]
            if tag in REQUIRED_COLUMNS:
                missing = [c for c in REQUIRED_COLUMNS[tag] if c not in cells[1:]]
                if missing:
                    findings.append(IIFGrammarFinding(
                        rule_id=IIF_GRAMMAR_ERROR,
                        severity="error",
                        message=f"IIF header !{tag} (line {lineno}) missing required columns: "
                                f"{', '.join(missing)}",
                    ))
            continue
        tag = cells[0]
        header = headers.get(tag)
        if header is None:
            continue
        record = dict(zip(header, cells[1:]))
        if tag == "ACCNT":
            at_raw = record.get("ACCNTTYPE", "").lower()
            at_map = {
                "asset": AccountType.ASSET,
                "bank": AccountType.ASSET,
                "liability": AccountType.LIABILITY,
                "equity": AccountType.EQUITY,
                "income": AccountType.REVENUE,
                "expense": AccountType.EXPENSE,
            }
            at = at_map.get(at_raw)
            accounts.append(Account(
                account_number=record.get("NAME", "").strip() or f"iif-{len(accounts)}",
                account_name=record.get("NAME", "").strip() or "Unknown",
                account_type=at,
            ))
        elif tag in ("TRNS", "SPL") and "ACCNT" in record and "AMOUNT" in record:
            amt_raw = record.get("AMOUNT", "0")
            try:
                amt = Decimal(amt_raw)
            except Exception:
                findings.append(IIFGrammarFinding(
                    rule_id=IIF_GRAMMAR_ERROR,
                    severity="error",
                    message=f"IIF {tag} line {lineno}: invalid AMOUNT {amt_raw!r}",
                ))
                continue
            debit = amt if amt > 0 else Decimal("0")
            credit = -amt if amt < 0 else Decimal("0")
            lines_out.append(ReportLine(
                line_id=f"{tag.lower()}-{lineno}",
                account=Account(
                    account_number=record["ACCNT"].strip() or "unknown",
                    account_name=record["ACCNT"].strip() or "Unknown",
                ),
                debit=debit,
                credit=credit,
                displayed_value=amt_raw,
                source_ref=SourceRef(document_id=doc_id),
            ))

    result = ParseResult(
        document_id=doc_id,
        report_type=ReportType.GENERAL_LEDGER,
        source_system="iif",
        parser_version="iif-0.1",
        parsed_at=datetime.now(timezone.utc),
        sections=(
            ReportSection(section_id="transactions", title="IIF Transactions",
                          lines=tuple(lines_out)),
        ),
    )
    return result, findings
