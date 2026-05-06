"""Interchange parser tests.

Run against the real vendor fixtures in tests/fixtures/vendor/ofxparse
(21 MIT-licensed OFX samples) and against the synthetic factory outputs
(OFX/QIF/IIF/XBRL).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from accounting_parser.interchange import (
    IIF_GRAMMAR_ERROR,
    parse_iif,
    parse_ofx,
    parse_qif,
    parse_xbrl,
)


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
VENDOR_OFX = REPO_ROOT / "tests" / "fixtures" / "vendor" / "ofxparse"


@pytest.mark.parametrize("fname", [
    "bank_medium.ofx",
    "checking.ofx",
    "fidelity.ofx",
    "vanguard.ofx",
    "td_ameritrade.ofx",
    "tiaacref.ofx",
    "investment_401k.ofx",
])
def test_parses_real_vendor_ofx_samples(fname: str) -> None:
    path = VENDOR_OFX / fname
    if not path.exists():
        pytest.skip(f"vendor OFX sample not present: {path}")
    result = parse_ofx(path)
    assert result.source_system == "ofx"
    # Most of these have at least one line (transaction) — a few edge-case
    # fixtures have zero. Only assert the parse didn't error.


def test_iif_malformed_produces_grammar_finding(tmp_path: Path) -> None:
    bad = tmp_path / "bad.iif"
    bad.write_text(
        "!TRNS\tDATE\tAMOUNT\tNAME\tMEMO\n"  # missing required ACCNT column
        "TRNS\t12/01/2024\t100.00\tVendor\tmemo\n",
        encoding="utf-8",
    )
    _, findings = parse_iif(bad)
    assert len(findings) >= 1
    assert findings[0].rule_id == IIF_GRAMMAR_ERROR
    assert "ACCNT" in findings[0].message


def test_iif_wellformed_produces_no_findings(tmp_path: Path) -> None:
    good = tmp_path / "good.iif"
    good.write_text(
        "!ACCNT\tNAME\tACCNTTYPE\n"
        "ACCNT\tCash\tASSET\n"
        "!TRNS\tTRNSID\tTRNSTYPE\tDATE\tACCNT\tAMOUNT\tNAME\tMEMO\n"
        "TRNS\t1\tGENERAL JOURNAL\t12/31/2024\tCash\t100.00\tX\tmemo\n",
        encoding="utf-8",
    )
    result, findings = parse_iif(good)
    assert findings == []
    assert len(result.sections) == 1


def test_qif_parses_basic_bank_record(tmp_path: Path) -> None:
    path = tmp_path / "s.qif"
    path.write_text(
        "!Type:Bank\n"
        "D12/03/2024\n"
        "T100.00\n"
        "PDeposit\n"
        "^\n"
        "D12/05/2024\n"
        "T-50.00\n"
        "PCheck\n"
        "^\n",
        encoding="utf-8",
    )
    result = parse_qif(path)
    lines = result.sections[0].lines
    assert len(lines) == 2
    assert lines[0].debit == 100
    assert lines[1].credit == 50


def test_xbrl_extracts_us_gaap_facts(tmp_path: Path) -> None:
    path = tmp_path / "s.xbrl"
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<xbrl xmlns="http://www.xbrl.org/2003/instance" '
        'xmlns:us-gaap="http://fasb.org/us-gaap/2024">\n'
        '  <us-gaap:Revenues contextRef="c1" unitRef="USD">1000000</us-gaap:Revenues>\n'
        '  <us-gaap:GrossProfit contextRef="c1" unitRef="USD">400000</us-gaap:GrossProfit>\n'
        "</xbrl>\n",
        encoding="utf-8",
    )
    result = parse_xbrl(path)
    line_ids = {ln.line_id for ln in result.sections[0].lines}
    assert "Revenues" in line_ids
    assert "GrossProfit" in line_ids
