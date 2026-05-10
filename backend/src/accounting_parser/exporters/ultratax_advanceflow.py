"""UltraTax CS + AdvanceFlow exporter — parent Task 19 / fork P2.5.

Emits a ZIP containing AdvanceFlow xlsx + UltraTax SDE xml in one
shot. Vendor-sandbox round-trip is a manual acceptance gate per
the spec.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from openpyxl import Workbook

from accounting_parser.exporters.base import (
    ExportBlocker,
    ExportResult,
    RefuseToEmit,
    TargetSystemAdapter,
)
from accounting_parser.model.canonical import WorkingTrialBalance


class UltraTaxAdvanceFlowAdapter(TargetSystemAdapter):
    target_system: str = "ultratax_advanceflow"

    def validate(self, wtb: WorkingTrialBalance) -> list[ExportBlocker]:
        blockers: list[ExportBlocker] = []

        unclassified = [r for r in wtb.rows if not r.account.category]
        if unclassified:
            blockers.append(
                ExportBlocker(
                    rule_id="ultratax.unclassified_accounts",
                    message=(
                        f"{len(unclassified)} account(s) lack classification; "
                        "UltraTax requires every account mapped before import."
                    ),
                )
            )

        if not wtb.rows:
            blockers.append(
                ExportBlocker(
                    rule_id="ultratax.empty_wtb",
                    message="WTB has no rows; nothing to export.",
                )
            )

        return blockers

    def emit(self, wtb: WorkingTrialBalance, output_dir: Path) -> ExportResult:
        blockers = self.validate(wtb)
        if blockers:
            raise RefuseToEmit(f"{len(blockers)} blocker(s) prevent emission")

        output_dir.mkdir(parents=True, exist_ok=True)
        zip_path = output_dir / f"ultratax_advanceflow_{wtb.engagement_id}.zip"

        advanceflow_bytes = _build_advanceflow_xlsx(wtb)
        ultratax_bytes = _build_ultratax_sde_xml(wtb)

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("advanceflow_import.xlsx", advanceflow_bytes)
            zf.writestr("ultratax_sde.xml", ultratax_bytes)

        return ExportResult(
            target_system=self.target_system,
            artifacts=(zip_path,),
            blockers=(),
        )


def _build_advanceflow_xlsx(wtb: WorkingTrialBalance) -> bytes:
    """AdvanceFlow-shaped xlsx; column headers per vendor public docs."""
    wb = Workbook()
    ws = wb.active
    ws.title = "TB Import"
    headers = [
        "Account_Number",
        "Account_Name",
        "Prior_Year",
        "Unadjusted",
        "AJE",
        "Adjusted",
        "RJE",
        "Final",
        "TJE",
        "Tax_Basis",
    ]
    ws.append(headers)
    for row in wtb.rows:
        ws.append(
            [
                row.account.account_number,
                row.account.account_name,
                float(row.prior_year),
                float(row.unadjusted),
                float(row.sum_aje),
                float(row.adjusted),
                float(row.sum_rje),
                float(row.final),
                float(row.sum_tje),
                float(row.tax_basis),
            ]
        )
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _build_ultratax_sde_xml(wtb: WorkingTrialBalance) -> bytes:
    """Minimal UltraTax Source Data Entry XML skeleton.

    Real installs populate fixed-asset + K-1 detail here. At P2.5
    the skeleton is emitted with just the engagement ref so
    AdvanceFlow + UltraTax can both chew the ZIP; deeper field
    mapping lands in subsequent work.
    """
    import xml.etree.ElementTree as ET

    root = ET.Element(
        "SourceDataEntry",
        attrib={
            "xmlns": "http://www.thomsonreuters.com/ultratax/sde/1.0",
            "engagement_id": str(wtb.engagement_id),
        },
    )
    # Placeholder sections so downstream importers see the structure
    # they expect even when no detail is populated yet.
    ET.SubElement(root, "FixedAssets")
    ET.SubElement(root, "K1Detail")

    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
