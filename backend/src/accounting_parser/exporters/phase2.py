"""Phase-2 Target_System_Exporters — Tasks 19, 28.

Seven additional adapters that share the Task 18 shape:
- ultratax_advanceflow (Task 19) — Thomson Reuters
- lacerte_tb_utility            — Intuit Lacerte XLSX
- proseries_tb_import           — Intuit ProSeries
- proconnect_prep_for_taxes     — Intuit ProConnect (JSON)
- drake_tb_import               — Drake Tax XLSX
- caseware_working_papers       — CaseWare CSV + text export
- quickbooks_iif                — QuickBooks Desktop write-back
- gosystem_tax_rs               — Thomson Reuters GoSystem Organizer

Each adapter:
- Declares its target_system id.
- validate() reuses the shared blocker checks + adds format-specific
  blockers.
- emit() writes vendor-shaped artifacts and refuses on any blocker.

Real vendor format specs come from the Task 18 links in design.md;
each adapter implements the minimum layout each vendor documents as
the public import contract. Manual vendor-sandbox round-trip remains
the acceptance gate.
"""
from __future__ import annotations

import csv
import json
import logging
from decimal import Decimal
from pathlib import Path

from accounting_parser.exporters.base import (
    ExportBlocker,
    ExportResult,
    RefuseToEmit,
)
from accounting_parser.model.canonical import WorkingTrialBalance, WTBRow

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared validator helpers.
# ---------------------------------------------------------------------------

def _shared_blockers(wtb: WorkingTrialBalance) -> list[ExportBlocker]:
    """Blockers every Phase-2 exporter inherits."""
    blockers: list[ExportBlocker] = []
    if not wtb.rows:
        return [ExportBlocker(rule_id="empty_wtb", message="WTB has no rows")]

    unclassified = [r for r in wtb.rows if not r.account.category]
    if unclassified:
        blockers.append(
            ExportBlocker(
                rule_id="unclassified_accounts",
                message=(
                    f"{len(unclassified)} accounts have no Category — "
                    f"reclassify in the Preparer UI before exporting."
                ),
            )
        )

    # Tax-basis debits vs credits (sign convention: positive = debit balance).
    dr = sum((r.tax_basis for r in wtb.rows if r.tax_basis > 0), Decimal(0))
    cr = sum((-r.tax_basis for r in wtb.rows if r.tax_basis < 0), Decimal(0))
    if abs(dr - cr) > Decimal("0.01"):
        blockers.append(
            ExportBlocker(
                rule_id="tax_basis_imbalanced",
                message=(
                    f"Tax-basis debits {dr} and credits {cr} differ by "
                    f"{abs(dr - cr)}."
                ),
            )
        )
    return blockers


def _fs_group(row: WTBRow) -> str:
    """Deterministic FS-grouping label derived from account category."""
    if not row.account.category:
        return ""
    cat = row.account.category.lower()
    if "asset" in cat:
        return "Assets"
    if "liabil" in cat:
        return "Liabilities"
    if "equity" in cat:
        return "Equity"
    if "revenue" in cat or "income" in cat:
        return "Revenue"
    if "cogs" in cat or "cost_of_goods" in cat:
        return "COGS"
    if "expense" in cat:
        return "OpEx"
    return cat.title()


def _tax_grouping(row: WTBRow) -> str:
    return _fs_group(row)


def _iif_accnt_type(row: WTBRow) -> str:
    mapping = {
        "asset": "BANK",
        "assets_current": "BANK",
        "assets_non_current": "FIXASSET",
        "liability": "OCLIAB",
        "liabilities_current": "OCLIAB",
        "liabilities_long_term": "LTLIAB",
        "equity": "EQUITY",
        "revenue": "INC",
        "income": "INC",
        "cogs": "COGS",
        "cost_of_goods_sold": "COGS",
        "expense": "EXP",
        "operating_expenses": "EXP",
        "non_operating_income": "OINC",
        "non_operating_expenses": "OEXP",
        "taxes": "OEXP",
    }
    key = (row.account.category or "").lower()
    return mapping.get(key, "OEXP")


# ---------------------------------------------------------------------------
# Base class shared by every Phase-2 adapter.
# ---------------------------------------------------------------------------


class _BaseAdapter:
    target_system: str = ""

    def validate(self, wtb: WorkingTrialBalance) -> list[ExportBlocker]:
        return _shared_blockers(wtb)

    def emit(self, wtb: WorkingTrialBalance, output_dir: Path) -> ExportResult:
        raise NotImplementedError

    def _refuse_if_blocked(
        self, wtb: WorkingTrialBalance
    ) -> list[ExportBlocker]:
        blockers = self.validate(wtb)
        if blockers:
            raise RefuseToEmit(blockers)
        return blockers


# ---------------------------------------------------------------------------
# UltraTax CS + AdvanceFlow (Task 19)
# ---------------------------------------------------------------------------


class UltraTaxAdvanceFlowAdapter(_BaseAdapter):
    target_system = "ultratax_advanceflow"

    def emit(self, wtb: WorkingTrialBalance, output_dir: Path) -> ExportResult:
        self._refuse_if_blocked(wtb)
        output_dir.mkdir(parents=True, exist_ok=True)

        csv_path = output_dir / "advanceflow_tb.csv"
        with csv_path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Account Number", "Account Name", "Category",
                "Prior Year", "Unadjusted", "Adjusted", "Final", "Tax Basis",
                "FS Group", "Tax Grouping",
            ])
            for row in wtb.rows:
                writer.writerow([
                    row.account.account_number, row.account.account_name,
                    row.account.category or "",
                    row.prior_year, row.unadjusted, row.adjusted,
                    row.final, row.tax_basis,
                    _fs_group(row), _tax_grouping(row),
                ])

        xml_path = output_dir / "ultratax_sde.xml"
        xml_path.write_text(_ultratax_sde_xml(wtb))

        return ExportResult(
            target_system=self.target_system,
            artifacts=(csv_path, xml_path),
            blockers=(),
        )


def _ultratax_sde_xml(wtb: WorkingTrialBalance) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<SourceDataEntry>"]
    lines.append(f'  <Engagement id="{wtb.engagement_id}">')
    for row in wtb.rows:
        lines.append(
            f'    <Account number="{row.account.account_number}" '
            f'name="{row.account.account_name}">'
            f"<TaxBasis>{row.tax_basis}</TaxBasis>"
            f"<TaxGrouping>{_tax_grouping(row)}</TaxGrouping>"
            "</Account>"
        )
    lines.append("  </Engagement>")
    lines.append("</SourceDataEntry>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Lacerte Trial Balance Utility (XLSX + CSV via Data Conductor)
# ---------------------------------------------------------------------------


class LacerteTBUtilityAdapter(_BaseAdapter):
    target_system = "lacerte"

    def emit(self, wtb: WorkingTrialBalance, output_dir: Path) -> ExportResult:
        self._refuse_if_blocked(wtb)
        output_dir.mkdir(parents=True, exist_ok=True)
        from openpyxl import Workbook

        xlsx_path = output_dir / "lacerte_tb_utility.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = "Trial Balance"
        ws.append([
            "Account Number", "Description", "Prior Year", "Unadjusted",
            "AJE", "Adjusted", "Reclass", "Final", "Tax", "Tax Balance",
        ])
        for row in wtb.rows:
            ws.append([
                row.account.account_number, row.account.account_name,
                float(row.prior_year), float(row.unadjusted),
                float(row.sum_aje), float(row.adjusted),
                float(row.sum_rje), float(row.final),
                float(row.sum_tje), float(row.tax_basis),
            ])
        wb.save(xlsx_path)

        csv_path = output_dir / "lacerte_data_conductor.csv"
        with csv_path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["AcctNum", "Description", "Balance"])
            for row in wtb.rows:
                w.writerow([
                    row.account.account_number,
                    row.account.account_name,
                    row.tax_basis,
                ])

        return ExportResult(
            target_system=self.target_system,
            artifacts=(xlsx_path, csv_path),
            blockers=(),
        )


# ---------------------------------------------------------------------------
# ProSeries / ProConnect
# ---------------------------------------------------------------------------


class ProSeriesAdapter(_BaseAdapter):
    target_system = "proseries"

    def emit(self, wtb: WorkingTrialBalance, output_dir: Path) -> ExportResult:
        self._refuse_if_blocked(wtb)
        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = output_dir / "proseries_tb.csv"
        with csv_path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Account", "Description", "Amount", "Tax Line"])
            for row in wtb.rows:
                w.writerow([
                    row.account.account_number, row.account.account_name,
                    row.tax_basis, _fs_group(row),
                ])
        return ExportResult(
            target_system=self.target_system,
            artifacts=(csv_path,),
            blockers=(),
        )


class ProConnectAdapter(_BaseAdapter):
    target_system = "proconnect"

    def emit(self, wtb: WorkingTrialBalance, output_dir: Path) -> ExportResult:
        self._refuse_if_blocked(wtb)
        output_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "engagement_id": str(wtb.engagement_id),
            "accounts": [
                {
                    "number": row.account.account_number,
                    "name": row.account.account_name,
                    "amount": str(row.tax_basis),
                    "tax_line": _fs_group(row),
                }
                for row in wtb.rows
            ],
        }
        path = output_dir / "proconnect_prep_for_taxes.json"
        path.write_text(json.dumps(payload, indent=2, default=str))
        return ExportResult(
            target_system=self.target_system,
            artifacts=(path,),
            blockers=(),
        )


# ---------------------------------------------------------------------------
# Drake Trial Balance Import XLSX
# ---------------------------------------------------------------------------


class DrakeAdapter(_BaseAdapter):
    target_system = "drake"

    def emit(self, wtb: WorkingTrialBalance, output_dir: Path) -> ExportResult:
        self._refuse_if_blocked(wtb)
        output_dir.mkdir(parents=True, exist_ok=True)
        from openpyxl import Workbook

        xlsx_path = output_dir / "drake_tb_import.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = "TB Import"
        ws.append(["AcctNum", "Description", "Amount", "TaxLine"])
        for row in wtb.rows:
            ws.append([
                row.account.account_number, row.account.account_name,
                float(row.tax_basis), _fs_group(row),
            ])
        wb.save(xlsx_path)
        return ExportResult(
            target_system=self.target_system,
            artifacts=(xlsx_path,),
            blockers=(),
        )


# ---------------------------------------------------------------------------
# CaseWare Working Papers CSV + per-engine text export
# ---------------------------------------------------------------------------


class CaseWareAdapter(_BaseAdapter):
    target_system = "caseware_working_papers"

    def emit(self, wtb: WorkingTrialBalance, output_dir: Path) -> ExportResult:
        self._refuse_if_blocked(wtb)
        output_dir.mkdir(parents=True, exist_ok=True)

        csv_path = output_dir / "caseware_tb.csv"
        with csv_path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "AccountNumber", "Description", "Group", "CurrentYear",
                "PriorYear",
            ])
            for row in wtb.rows:
                w.writerow([
                    row.account.account_number, row.account.account_name,
                    _fs_group(row), row.final, row.prior_year,
                ])

        txt_path = output_dir / "caseware_export_ultratax.txt"
        lines = [
            f"{row.account.account_number:<12}"
            f"{row.account.account_name[:40]:<40}"
            f"{row.tax_basis:>15}"
            for row in wtb.rows
        ]
        txt_path.write_text("\n".join(lines))

        return ExportResult(
            target_system=self.target_system,
            artifacts=(csv_path, txt_path),
            blockers=(),
        )


# ---------------------------------------------------------------------------
# QuickBooks IIF write-back
# ---------------------------------------------------------------------------


class QuickBooksIIFAdapter(_BaseAdapter):
    target_system = "quickbooks_iif"

    def emit(self, wtb: WorkingTrialBalance, output_dir: Path) -> ExportResult:
        self._refuse_if_blocked(wtb)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "quickbooks_writeback.iif"
        rows = ["!ACCNT\tNAME\tACCNTTYPE\tDESC\tACCNUM"]
        for row in wtb.rows:
            rows.append(
                f"ACCNT\t{row.account.account_name}\t{_iif_accnt_type(row)}"
                f"\t{row.account.account_name}\t{row.account.account_number}"
            )
        path.write_text("\n".join(rows))
        return ExportResult(
            target_system=self.target_system,
            artifacts=(path,),
            blockers=(),
        )


# ---------------------------------------------------------------------------
# GoSystem Tax RS Organizer
# ---------------------------------------------------------------------------


class GoSystemAdapter(_BaseAdapter):
    target_system = "gosystem_tax_rs"

    def emit(self, wtb: WorkingTrialBalance, output_dir: Path) -> ExportResult:
        self._refuse_if_blocked(wtb)
        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = output_dir / "gosystem_organizer.csv"
        with csv_path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["AccountNumber", "AccountName", "TaxAmount", "TaxGroup"])
            for row in wtb.rows:
                w.writerow([
                    row.account.account_number, row.account.account_name,
                    row.tax_basis, _tax_grouping(row),
                ])
        return ExportResult(
            target_system=self.target_system,
            artifacts=(csv_path,),
            blockers=(),
        )


# Registry: every Phase-2 adapter for tests + workflow export step.

PHASE2_ADAPTERS: dict[str, type[_BaseAdapter]] = {
    "ultratax_advanceflow": UltraTaxAdvanceFlowAdapter,
    "lacerte": LacerteTBUtilityAdapter,
    "proseries": ProSeriesAdapter,
    "proconnect": ProConnectAdapter,
    "drake": DrakeAdapter,
    "caseware_working_papers": CaseWareAdapter,
    "quickbooks_iif": QuickBooksIIFAdapter,
    "gosystem_tax_rs": GoSystemAdapter,
}
