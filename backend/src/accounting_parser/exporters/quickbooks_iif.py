"""QuickBooks IIF write-back exporter — parent Task 28 / fork P2.5."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from accounting_parser.exporters.base import (
    ExportBlocker,
    ExportResult,
    RefuseToEmit,
    TargetSystemAdapter,
)
from accounting_parser.model.canonical import WorkingTrialBalance


class QuickBooksIifAdapter(TargetSystemAdapter):
    target_system: str = "quickbooks_iif"

    def validate(self, wtb: WorkingTrialBalance) -> list[ExportBlocker]:
        blockers: list[ExportBlocker] = []
        if not any(r.sum_aje for r in wtb.rows):
            blockers.append(
                ExportBlocker(
                    rule_id="quickbooks_iif.no_adjustments",
                    message=(
                        "No adjustment entries to write; QuickBooks IIF "
                        "write-back is adjustment-only — nothing to emit."
                    ),
                )
            )
        return blockers

    def emit(self, wtb: WorkingTrialBalance, output_dir: Path) -> ExportResult:
        blockers = self.validate(wtb)
        if blockers:
            raise RefuseToEmit(f"{len(blockers)} blocker(s) prevent emission")

        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"quickbooks_adjustments_{wtb.engagement_id}.iif"

        period_end = date.today().isoformat()

        lines: list[str] = []
        lines.append("!TRNS\tTRNSID\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tMEMO")
        lines.append("!SPL\tSPLID\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tMEMO")
        lines.append("!ENDTRNS")

        for i, row in enumerate(wtb.rows, start=1):
            if not row.sum_aje:
                continue
            amount = f"{float(row.sum_aje):.2f}"
            neg = f"{-float(row.sum_aje):.2f}"
            lines.append(
                f"TRNS\t{i}\tGENERAL JOURNAL\t{period_end}\t"
                f"{row.account.account_name}\t\t{amount}\taccounting-parser AJE"
            )
            lines.append(
                f"SPL\t{i}\tGENERAL JOURNAL\t{period_end}\t"
                f"{row.account.account_name}\t\t{neg}\toffset"
            )
            lines.append("ENDTRNS")

        # IIF must use CRLF line terminators per QuickBooks spec.
        path.write_bytes(("\r\n".join(lines) + "\r\n").encode("ascii"))

        return ExportResult(
            target_system=self.target_system,
            artifacts=(path,),
            blockers=(),
        )
