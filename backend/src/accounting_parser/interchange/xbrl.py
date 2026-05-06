"""XBRL (inline or instance) parser — minimal implementation.

Full XBRL parsing requires Arelle + a taxonomy resolver. That's deferred.
This MVP version extracts us-gaap facts from an instance document using
lxml element parsing — good enough to validate our fixtures and feed
smoke tests. Task 28 / production integration will swap in Arelle.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

from lxml import etree

from accounting_parser.model.canonical import (
    Account,
    ParseResult,
    ReportLine,
    ReportSection,
    ReportType,
    SourceRef,
)


US_GAAP_NS = "http://fasb.org/us-gaap/2024"


def parse_xbrl(
    xbrl_path: Path, *, document_id: UUID | None = None,
) -> ParseResult:
    doc_id = document_id or uuid4()
    tree = etree.parse(str(xbrl_path))  # noqa: S320 (trusted fixture paths)
    root = tree.getroot()

    # Collect every element whose namespace is us-gaap and whose text parses
    # as a decimal. Simple fact extraction only.
    facts: list[ReportLine] = []
    for el in root.iter():
        tag = el.tag
        if not isinstance(tag, str):
            continue
        if US_GAAP_NS not in tag:
            continue
        if not el.text or not el.text.strip():
            continue
        try:
            value = Decimal(el.text.strip())
        except Exception:
            continue
        local_name = tag.split("}", 1)[-1]
        facts.append(ReportLine(
            line_id=local_name,
            account=Account(
                account_number=f"us-gaap:{local_name}",
                account_name=local_name,
            ),
            balance=value,
            displayed_value=el.text,
            source_ref=SourceRef(document_id=doc_id),
        ))

    return ParseResult(
        document_id=doc_id,
        report_type=ReportType.OTHER,
        source_system="xbrl",
        parser_version="xbrl-0.1-minimal",
        parsed_at=datetime.now(timezone.utc),
        sections=(
            ReportSection(section_id="us-gaap-facts", title="us-gaap facts",
                          lines=tuple(facts)),
        ),
    )
