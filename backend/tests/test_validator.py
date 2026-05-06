"""Validator property tests — Correctness Property 9.

For every arbitrary Trial_Balance ParseResult, either:
    abs(sum(debits) - sum(credits)) <= tolerance
    OR
    at least one Validator error finding is produced.

Covers R9.1 through R9.7.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import hypothesis.strategies as st
from hypothesis import HealthCheck, given, settings

from accounting_parser.model.canonical import (
    Account,
    AccountType,
    ParseResult,
    ReportLine,
    ReportSection,
    ReportType,
    WorkingTrialBalance,
    WTBRow,
)
from accounting_parser.validator import (
    DEFAULT_TOLERANCE,
    Severity,
    validate_balance_sheet_ties,
    validate_trial_balance,
    validate_wtb_tie_out,
)


UTC = timezone.utc


# ---------- Strategies ----------

money = st.decimals(min_value=Decimal("0"), max_value=Decimal("100000"), places=2)


@st.composite
def tb_parse_result(draw):
    """Generate a TB with arbitrary debits and credits."""
    n = draw(st.integers(min_value=1, max_value=20))
    lines = []
    for i in range(n):
        is_debit = draw(st.booleans())
        amt = draw(money)
        at = draw(st.sampled_from(AccountType))
        lines.append(ReportLine(
            line_id=f"L{i}",
            account=Account(
                account_number=f"{1000+i}",
                account_name=f"Acct{i}",
                account_type=at,
                normal_balance=None,
            ),
            debit=amt if is_debit else Decimal("0"),
            credit=Decimal("0") if is_debit else amt,
        ))
    return ParseResult(
        document_id=uuid4(),
        report_type=ReportType.TRIAL_BALANCE,
        parser_version="test",
        parsed_at=datetime(2025, 1, 1, tzinfo=UTC),
        sections=(ReportSection(section_id="S1", title="All", lines=tuple(lines)),),
    )


@given(tb_parse_result())
@settings(max_examples=1000, deadline=None,
          suppress_health_check=[HealthCheck.filter_too_much])
def test_tb_either_balances_or_has_error_finding(pr: ParseResult) -> None:
    """Correctness Property 9."""
    findings = validate_trial_balance(pr)
    lines = [ln for s in pr.sections for ln in s.lines]
    total_dr = sum((ln.debit for ln in lines), Decimal("0"))
    total_cr = sum((ln.credit for ln in lines), Decimal("0"))
    diff = abs(total_dr - total_cr)
    if diff <= DEFAULT_TOLERANCE:
        assert not any(f.severity == Severity.ERROR for f in findings)
    else:
        assert any(f.severity == Severity.ERROR for f in findings), (
            f"TB out of balance by {diff} but validator produced no error finding"
        )


def test_balanced_tb_produces_no_findings() -> None:
    """A deliberately balanced TB: no findings."""
    pr = ParseResult(
        document_id=uuid4(),
        report_type=ReportType.TRIAL_BALANCE,
        parser_version="test",
        parsed_at=datetime(2025, 1, 1, tzinfo=UTC),
        sections=(ReportSection(section_id="S", title="All", lines=(
            ReportLine(
                line_id="1",
                account=Account(account_number="1000", account_name="Cash"),
                debit=Decimal("500.00"),
            ),
            ReportLine(
                line_id="2",
                account=Account(account_number="3000", account_name="Equity"),
                credit=Decimal("500.00"),
            ),
        )),),
    )
    assert validate_trial_balance(pr) == []


def test_unbalanced_tb_produces_error_finding() -> None:
    """An off-by-$50 TB: exactly one error finding."""
    pr = ParseResult(
        document_id=uuid4(),
        report_type=ReportType.TRIAL_BALANCE,
        parser_version="test",
        parsed_at=datetime(2025, 1, 1, tzinfo=UTC),
        sections=(ReportSection(section_id="S", title="All", lines=(
            ReportLine(
                line_id="1",
                account=Account(account_number="1000", account_name="Cash"),
                debit=Decimal("500.00"),
            ),
            ReportLine(
                line_id="2",
                account=Account(account_number="3000", account_name="Equity"),
                credit=Decimal("450.00"),
            ),
        )),),
    )
    findings = validate_trial_balance(pr)
    assert len(findings) == 1
    assert findings[0].severity == Severity.ERROR
    assert findings[0].rule_id == "R9.1.tb_balance"


def test_balance_sheet_ties_happy_path() -> None:
    pr = ParseResult(
        document_id=uuid4(),
        report_type=ReportType.BALANCE_SHEET,
        parser_version="test",
        parsed_at=datetime(2025, 1, 1, tzinfo=UTC),
        sections=(ReportSection(section_id="S", title="BS", lines=(
            ReportLine(
                line_id="1",
                account=Account(account_number="1000", account_name="Cash",
                                account_type=AccountType.ASSET),
                balance=Decimal("1000.00"),
            ),
            ReportLine(
                line_id="2",
                account=Account(account_number="2000", account_name="AP",
                                account_type=AccountType.LIABILITY),
                balance=Decimal("400.00"),
            ),
            ReportLine(
                line_id="3",
                account=Account(account_number="3000", account_name="Equity",
                                account_type=AccountType.EQUITY),
                balance=Decimal("600.00"),
            ),
        )),),
    )
    findings = validate_balance_sheet_ties(pr)
    assert findings == []


def test_wtb_tie_out_violation() -> None:
    wtb = WorkingTrialBalance(engagement_id=uuid4(), rows=(
        WTBRow(
            account=Account(account_number="1000", account_name="Cash"),
            unadjusted=Decimal("1000.00"),
            sum_aje=Decimal("100.00"),
            adjusted=Decimal("1200.00"),  # off by 100
            sum_rje=Decimal("0"),
            final=Decimal("1200.00"),
            sum_tje=Decimal("0"),
            tax_basis=Decimal("1200.00"),
        ),
    ))
    findings = validate_wtb_tie_out(wtb)
    assert any(f.rule_id == "R9.7.wtb_tie_out.unadjusted+aje=adjusted" for f in findings)
