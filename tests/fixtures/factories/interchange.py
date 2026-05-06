"""Interchange-format factories: OFX, QFX, QIF, IIF, XBRL.

These are simple text-based formats. The parser tests in Task 11 use the
standard libraries (``ofxparse``, ``arelle``) — our factories just need to
produce grammatically-valid output with realistic content.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from textwrap import dedent

from factories._data import DEFAULT_CHART, balanced_debits_credits


# ------------------------- OFX / QFX -------------------------


_OFX_HEADER = dedent(
    """\
    OFXHEADER:100
    DATA:OFXSGML
    VERSION:102
    SECURITY:NONE
    ENCODING:USASCII
    CHARSET:1252
    COMPRESSION:NONE
    OLDFILEUID:NONE
    NEWFILEUID:NONE

    """
)


def _ofx_body(bank_id: str = "123456789", account_id: str = "9876543210") -> str:
    return dedent(
        f"""\
        <OFX>
          <SIGNONMSGSRSV1>
            <SONRS>
              <STATUS><CODE>0</CODE><SEVERITY>INFO</SEVERITY></STATUS>
              <DTSERVER>20241231120000</DTSERVER>
              <LANGUAGE>ENG</LANGUAGE>
            </SONRS>
          </SIGNONMSGSRSV1>
          <BANKMSGSRSV1>
            <STMTTRNRS>
              <TRNUID>1001</TRNUID>
              <STATUS><CODE>0</CODE><SEVERITY>INFO</SEVERITY></STATUS>
              <STMTRS>
                <CURDEF>USD</CURDEF>
                <BANKACCTFROM>
                  <BANKID>{bank_id}</BANKID>
                  <ACCTID>{account_id}</ACCTID>
                  <ACCTTYPE>CHECKING</ACCTTYPE>
                </BANKACCTFROM>
                <BANKTRANLIST>
                  <DTSTART>20241201</DTSTART>
                  <DTEND>20241231</DTEND>
                  <STMTTRN>
                    <TRNTYPE>CREDIT</TRNTYPE>
                    <DTPOSTED>20241203</DTPOSTED>
                    <TRNAMT>4567.89</TRNAMT>
                    <FITID>F00001</FITID>
                    <NAME>ACH DEPOSIT - PAYROLL</NAME>
                  </STMTTRN>
                  <STMTTRN>
                    <TRNTYPE>DEBIT</TRNTYPE>
                    <DTPOSTED>20241205</DTPOSTED>
                    <TRNAMT>-123.45</TRNAMT>
                    <FITID>F00002</FITID>
                    <NAME>POS PURCHASE - STAPLES</NAME>
                  </STMTTRN>
                  <STMTTRN>
                    <TRNTYPE>DEBIT</TRNTYPE>
                    <DTPOSTED>20241208</DTPOSTED>
                    <TRNAMT>-2345.67</TRNAMT>
                    <FITID>F00003</FITID>
                    <NAME>WIRE TRANSFER OUT</NAME>
                  </STMTTRN>
                </BANKTRANLIST>
                <LEDGERBAL>
                  <BALAMT>12099.77</BALAMT>
                  <DTASOF>20241231</DTASOF>
                </LEDGERBAL>
              </STMTRS>
            </STMTTRNRS>
          </BANKMSGSRSV1>
        </OFX>
        """
    )


def ofx_factory(output_path: Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_OFX_HEADER + _ofx_body(), encoding="us-ascii")
    return output_path


def qfx_factory(output_path: Path) -> Path:
    """QFX is OFX with Intuit extensions. For parser tests the body is the same."""
    return ofx_factory(output_path)


# ------------------------- QIF -------------------------


def qif_factory(output_path: Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = dedent(
        """\
        !Type:Bank
        D12/03/2024
        T4567.89
        PACH Deposit - Payroll
        ^
        D12/05/2024
        T-123.45
        PPOS Purchase - Staples
        ^
        D12/08/2024
        T-2345.67
        PWire Transfer Out
        ^
        D12/10/2024
        T-500.00
        PCheck #1234
        N1234
        ^
        """
    )
    output_path.write_text(content, encoding="utf-8")
    return output_path


# ------------------------- IIF -------------------------


def iif_factory(output_path: Path, *, malformed: bool = False) -> Path:
    """Generate a QuickBooks IIF general-journal import file.

    Args:
        output_path: Target.
        malformed: If True, drops a required header column so parser grammar
            tests can exercise the rejection path.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    accs = DEFAULT_CHART[:6]
    debits, credits = balanced_debits_credits(accs)
    # Pick first debit account and first credit account for the journal
    dr_accs = [a for a in accs if a.normal_balance == "debit"][:1]
    cr_accs = [a for a in accs if a.normal_balance == "credit"][:1]

    if malformed:
        # Missing the ACCNT column in TRNS header — invalid grammar
        header_trns = "!TRNS\tDATE\tAMOUNT\tNAME\tMEMO\n"
    else:
        header_trns = "!TRNS\tTRNSID\tTRNSTYPE\tDATE\tACCNT\tAMOUNT\tNAME\tMEMO\n"

    lines: list[str] = [
        "!ACCNT\tNAME\tACCNTTYPE\n",
        *(f"ACCNT\t{a.name}\t{a.type.upper()}\n" for a in accs),
        "!ENDGRP\n",
        header_trns,
        "!SPL\tSPLID\tTRNSTYPE\tDATE\tACCNT\tAMOUNT\tMEMO\n",
        "!ENDTRNS\n",
    ]

    if not malformed:
        lines.append(
            f"TRNS\t1\tGENERAL JOURNAL\t12/31/2024\t{dr_accs[0].name}\t{debits:.2f}\tSample JE\tDR leg\n"
        )
        lines.append(
            f"SPL\t2\tGENERAL JOURNAL\t12/31/2024\t{cr_accs[0].name}\t-{credits:.2f}\tCR leg\n"
        )
        lines.append("ENDTRNS\n")

    output_path.write_text("".join(lines), encoding="utf-8")
    return output_path


# ------------------------- XBRL -------------------------


def xbrl_factory(output_path: Path) -> Path:
    """Generate a minimal XBRL instance document (US-GAAP taxonomy stub).

    Real XBRL requires a full taxonomy resolver. For parser tests we
    generate the instance document only; Task 11 wires up Arelle which
    expects a full taxonomy — marked as a known limitation in the test.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = dedent(
        """\
        <?xml version="1.0" encoding="UTF-8"?>
        <xbrl xmlns="http://www.xbrl.org/2003/instance"
              xmlns:xlink="http://www.w3.org/1999/xlink"
              xmlns:us-gaap="http://fasb.org/us-gaap/2024"
              xmlns:dei="http://xbrl.sec.gov/dei/2024"
              xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
          <context id="ctx_2024">
            <entity>
              <identifier scheme="http://www.sec.gov/CIK">0000000000</identifier>
            </entity>
            <period>
              <startDate>2024-01-01</startDate>
              <endDate>2024-12-31</endDate>
            </period>
          </context>
          <unit id="USD">
            <measure>iso4217:USD</measure>
          </unit>
          <us-gaap:Revenues contextRef="ctx_2024" unitRef="USD" decimals="0">1469135.78</us-gaap:Revenues>
          <us-gaap:CostOfGoodsSold contextRef="ctx_2024" unitRef="USD" decimals="0">567890.12</us-gaap:CostOfGoodsSold>
          <us-gaap:GrossProfit contextRef="ctx_2024" unitRef="USD" decimals="0">901245.66</us-gaap:GrossProfit>
        </xbrl>
        """
    )
    output_path.write_text(content, encoding="utf-8")
    return output_path
