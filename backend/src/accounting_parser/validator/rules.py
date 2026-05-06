"""Pure validation rules per Report_Type.

Each ``validate_*`` function takes the appropriate parsed model and returns
a list of Finding records. Default monetary tolerance is 0.01 (one cent),
configurable per call.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from accounting_parser.model.canonical import (
    Account,
    ParseResult,
    ReportSection,
    ReportType,
    WorkingTrialBalance,
)
from accounting_parser.validator.findings import Finding, Severity


DEFAULT_TOLERANCE: Decimal = Decimal("0.01")


def _lines(sections: Iterable[ReportSection]) -> list:
    """Flatten all lines across top-level + nested sections."""
    out: list = []
    for s in sections:
        out.extend(s.lines)
        out.extend(_lines(s.subsections))
    return out


# ---------- R9.1 Trial Balance debits == credits ----------


def validate_trial_balance(
    pr: ParseResult, *, tolerance: Decimal = DEFAULT_TOLERANCE
) -> list[Finding]:
    """R9.1: sum(debits) == sum(credits) across the TB."""
    findings: list[Finding] = []
    lines = _lines(pr.sections)
    debits = sum((ln.debit for ln in lines), Decimal("0"))
    credits = sum((ln.credit for ln in lines), Decimal("0"))
    diff = debits - credits
    if abs(diff) > tolerance:
        findings.append(Finding(
            rule_id="R9.1.tb_balance",
            severity=Severity.ERROR,
            message=f"Trial balance out of balance by {diff}",
            expected=f"{credits}",
            observed=f"{debits}",
            tolerance=tolerance,
        ))
    return findings


# ---------- R9.2 Balance Sheet Assets = Liabilities + Equity ----------


def validate_balance_sheet_ties(
    pr: ParseResult, *, tolerance: Decimal = DEFAULT_TOLERANCE
) -> list[Finding]:
    """R9.2: Assets == Liabilities + Equity.

    Uses account_type on each ReportLine's Account. Lines with unknown
    account_type are skipped with a warning finding.
    """
    findings: list[Finding] = []
    assets = Decimal("0")
    liab = Decimal("0")
    equity = Decimal("0")
    unknown = 0
    for ln in _lines(pr.sections):
        at = ln.account.account_type
        amount = ln.balance if ln.balance != 0 else ln.debit - ln.credit
        if at is None:
            unknown += 1
            continue
        name = at.value if hasattr(at, "value") else str(at)
        if name == "asset":
            assets += amount
        elif name == "liability":
            liab += amount
        elif name == "equity":
            equity += amount

    if unknown:
        findings.append(Finding(
            rule_id="R9.2.unclassified_accounts",
            severity=Severity.WARNING,
            message=f"{unknown} account(s) lack account_type; "
                    "balance-sheet tie-out may be incomplete",
        ))

    diff = assets - (liab + equity)
    if abs(diff) > tolerance:
        findings.append(Finding(
            rule_id="R9.2.bs_tie_out",
            severity=Severity.ERROR,
            message=f"Balance sheet out of balance by {diff}",
            expected=f"{liab + equity}",
            observed=f"{assets}",
            tolerance=tolerance,
        ))
    return findings


# ---------- R9.3 Subtotals foot to detail lines ----------


def validate_subtotals_foot(
    pr: ParseResult, *, tolerance: Decimal = DEFAULT_TOLERANCE
) -> list[Finding]:
    """R9.3: each ReportSection's stated subtotal == sum of its lines' balances.

    This rule only triggers for sections whose title contains 'Total' — those
    are the subtotal rows. Remaining sections are skipped.
    """
    findings: list[Finding] = []
    for section in pr.sections:
        if "total" not in section.title.lower():
            continue
        if not section.lines:
            continue
        # Convention: last line is the stated total, preceding lines are details
        *details, total_line = section.lines
        detail_sum = sum((ln.balance for ln in details), Decimal("0"))
        if abs(detail_sum - total_line.balance) > tolerance:
            findings.append(Finding(
                rule_id="R9.3.subtotal_foot",
                severity=Severity.ERROR,
                message=f"Subtotal in section {section.section_id!r} "
                        f"does not foot: detail sum {detail_sum} vs stated {total_line.balance}",
                expected=f"{detail_sum}",
                observed=f"{total_line.balance}",
                tolerance=tolerance,
            ))
    return findings


# ---------- R9.4 AR aging total ----------


def validate_ar_aging(
    pr: ParseResult, *, tolerance: Decimal = DEFAULT_TOLERANCE
) -> list[Finding]:
    """R9.4: AR aging bucket sum == total AR balance."""
    return _validate_aging(pr, "R9.4.ar_aging", tolerance)


def validate_ap_aging(
    pr: ParseResult, *, tolerance: Decimal = DEFAULT_TOLERANCE
) -> list[Finding]:
    """R9.5: AP aging bucket sum == total AP balance."""
    return _validate_aging(pr, "R9.5.ap_aging", tolerance)


def _validate_aging(
    pr: ParseResult, rule_id: str, tolerance: Decimal
) -> list[Finding]:
    # Skip if not an aging report
    if pr.report_type not in (ReportType.AR_AGING, ReportType.AP_AGING):
        return []
    findings: list[Finding] = []
    lines = _lines(pr.sections)
    if not lines:
        return []
    # Convention: last line is the total, rest are bucket rows
    *buckets, total_line = lines
    bucket_sum = sum((ln.balance for ln in buckets), Decimal("0"))
    if abs(bucket_sum - total_line.balance) > tolerance:
        findings.append(Finding(
            rule_id=rule_id,
            severity=Severity.ERROR,
            message=f"Aging totals do not match: buckets sum {bucket_sum} "
                    f"vs stated total {total_line.balance}",
            expected=f"{bucket_sum}",
            observed=f"{total_line.balance}",
            tolerance=tolerance,
        ))
    return findings


# ---------- R9.6 Bank statement beginning + activity = ending ----------


def validate_bank_statement(
    pr: ParseResult,
    *,
    beginning: Decimal,
    ending: Decimal,
    tolerance: Decimal = DEFAULT_TOLERANCE,
) -> list[Finding]:
    """R9.6: beginning balance + sum(transactions) == ending balance."""
    if pr.report_type != ReportType.BANK_STATEMENT:
        return []
    findings: list[Finding] = []
    activity = sum(
        ((ln.debit - ln.credit) for ln in _lines(pr.sections)),
        Decimal("0"),
    )
    computed = beginning + activity
    if abs(computed - ending) > tolerance:
        findings.append(Finding(
            rule_id="R9.6.bank_statement_balance",
            severity=Severity.ERROR,
            message=f"Bank statement does not balance: {beginning} + "
                    f"{activity} = {computed}, expected ending {ending}",
            expected=f"{ending}",
            observed=f"{computed}",
            tolerance=tolerance,
        ))
    return findings


# ---------- R9.7 WTB column tie-out ----------


def validate_wtb_tie_out(
    wtb: WorkingTrialBalance, *, tolerance: Decimal = DEFAULT_TOLERANCE
) -> list[Finding]:
    """R9.7: for every row, unadjusted + sum_aje == adjusted (within tolerance).

    Also enforces adjusted + sum_rje == final, and final + sum_tje == tax_basis.
    """
    findings: list[Finding] = []
    for row in wtb.rows:
        acc = row.account.account_number
        for label, lhs_a, lhs_b, rhs in (
            ("unadjusted+aje=adjusted", row.unadjusted, row.sum_aje, row.adjusted),
            ("adjusted+rje=final", row.adjusted, row.sum_rje, row.final),
            ("final+tje=tax_basis", row.final, row.sum_tje, row.tax_basis),
        ):
            diff = (lhs_a + lhs_b) - rhs
            if abs(diff) > tolerance:
                findings.append(Finding(
                    rule_id=f"R9.7.wtb_tie_out.{label}",
                    severity=Severity.ERROR,
                    message=f"WTB tie-out for account {acc}: {label} "
                            f"violated by {diff}",
                    expected=f"{lhs_a + lhs_b}",
                    observed=f"{rhs}",
                    tolerance=tolerance,
                ))
    return findings


# ---------- Dispatcher ----------


def validate_parse_result(
    pr: ParseResult, *, tolerance: Decimal = DEFAULT_TOLERANCE
) -> list[Finding]:
    """Route to the right validators by Report_Type."""
    findings: list[Finding] = []
    if pr.report_type == ReportType.TRIAL_BALANCE:
        findings.extend(validate_trial_balance(pr, tolerance=tolerance))
        findings.extend(validate_subtotals_foot(pr, tolerance=tolerance))
    elif pr.report_type == ReportType.BALANCE_SHEET:
        findings.extend(validate_balance_sheet_ties(pr, tolerance=tolerance))
        findings.extend(validate_subtotals_foot(pr, tolerance=tolerance))
    elif pr.report_type == ReportType.AR_AGING:
        findings.extend(validate_ar_aging(pr, tolerance=tolerance))
    elif pr.report_type == ReportType.AP_AGING:
        findings.extend(validate_ap_aging(pr, tolerance=tolerance))
    return findings
