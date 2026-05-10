"""Lacerte Trial Balance Utility exporter — parent Task 28 / fork P2.5."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from accounting_parser.exporters.base import (
    ExportBlocker,
    ExportResult,
    RefuseToEmit,
    TargetSystemAdapter,
)
from accounting_parser.model.canonical import AccountType, WorkingTrialBalance

_LACERTE_TYPE_CODES = {
    AccountType.ASSET: "1",
    AccountType.LIABILITY: "2",
    AccountType.EQUITY: "3",
    AccountType.REVENUE: "4",
    AccountType.EXPENSE: "5",
}


class LacerteAdapter(TargetSystemAdapter):
    target_system: str = "lacerte_tb_utility"

    def validate(self, wtb: WorkingTrialBalance) -> list[ExportBlocker]:
        blockers: list[ExportBlocker] = []
        unmapped = [r for r in wtb.rows if r.account.account_type not in _LACERTE_TYPE_CODES]
        if unmapped:
            blockers.append(
                ExportBlocker(
                    rule_id="lacerte.unmapped_account_type",
                    message=(
                        f"{len(unmapped)} account(s) lack a Lacerte-compatible "
                        "account_type (asset/liability/equity/revenue/expense)."
                    ),
                )
            )
        return blockers

    def emit(self, wtb: WorkingTrialBalance, output_dir: Path) -> ExportResult:
        blockers = self.validate(wtb)
        if blockers:
            raise RefuseToEmit(f"{len(blockers)} blocker(s) prevent emission")

        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"lacerte_tb_{wtb.engagement_id}.txt"

        buf = io.StringIO()
        writer = csv.writer(buf, delimiter="\t", lineterminator="\n")
        writer.writerow(["AccountNumber", "AccountName", "AccountType", "AdjustedBalance"])
        for row in wtb.rows:
            writer.writerow(
                [
                    row.account.account_number,
                    row.account.account_name,
                    _LACERTE_TYPE_CODES[row.account.account_type],
                    f"{row.adjusted:.2f}",
                ]
            )
        path.write_text(buf.getvalue(), encoding="utf-8")

        return ExportResult(
            target_system=self.target_system,
            artifacts=(path,),
            blockers=(),
        )
