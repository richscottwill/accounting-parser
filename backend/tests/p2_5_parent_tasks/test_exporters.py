"""Parent Task 19 + Task 28 exporter adapters."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from accounting_parser.exporters.base import RefuseToEmit
from accounting_parser.exporters.lacerte import LacerteAdapter
from accounting_parser.exporters.quickbooks_iif import QuickBooksIifAdapter
from accounting_parser.exporters.ultratax_advanceflow import UltraTaxAdvanceFlowAdapter
from accounting_parser.model.canonical import Account, AccountType, WorkingTrialBalance, WTBRow


def _row(
    *,
    number: str,
    name: str,
    account_type: AccountType,
    category: str | None = "classified",
    adjusted: str = "0",
    sum_aje: str = "0",
) -> WTBRow:
    return WTBRow(
        account=Account(
            account_number=number,
            account_name=name,
            account_type=account_type,
            category=category,
        ),
        adjusted=Decimal(adjusted),
        sum_aje=Decimal(sum_aje),
    )


def _wtb(rows: list[WTBRow] | None = None) -> WorkingTrialBalance:
    if rows is None:
        rows = [
            _row(
                number="1000",
                name="Cash",
                account_type=AccountType.ASSET,
                adjusted="1200.00",
            ),
            _row(
                number="2000",
                name="Accrued Expenses",
                account_type=AccountType.LIABILITY,
                adjusted="500.00",
                sum_aje="500.00",
            ),
        ]
    return WorkingTrialBalance(engagement_id=uuid4(), rows=tuple(rows))


def test_ultratax_adapter_blocks_on_unclassified(tmp_path: Path):
    wtb = _wtb(
        [
            _row(
                number="9999",
                name="Mystery",
                account_type=AccountType.ASSET,
                category=None,
            ),
        ]
    )
    adapter = UltraTaxAdvanceFlowAdapter()
    blockers = adapter.validate(wtb)
    assert any(b.rule_id == "ultratax.unclassified_accounts" for b in blockers)


def test_ultratax_adapter_blocks_on_empty_wtb(tmp_path: Path):
    wtb = _wtb([])
    adapter = UltraTaxAdvanceFlowAdapter()
    blockers = adapter.validate(wtb)
    assert any(b.rule_id == "ultratax.empty_wtb" for b in blockers)


def test_ultratax_adapter_refuses_emit_on_blockers(tmp_path: Path):
    adapter = UltraTaxAdvanceFlowAdapter()
    with pytest.raises(RefuseToEmit):
        adapter.emit(_wtb([]), tmp_path)


def test_ultratax_adapter_emits_zip_with_both_artifacts(tmp_path: Path):
    adapter = UltraTaxAdvanceFlowAdapter()
    result = adapter.emit(_wtb(), tmp_path)
    assert result.target_system == "ultratax_advanceflow"
    assert len(result.artifacts) == 1
    zip_path = result.artifacts[0]
    assert zip_path.suffix == ".zip"
    import zipfile

    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
    assert "advanceflow_import.xlsx" in names
    assert "ultratax_sde.xml" in names


def test_lacerte_adapter_emits_tab_delimited(tmp_path: Path):
    adapter = LacerteAdapter()
    result = adapter.emit(_wtb(), tmp_path)
    content = result.artifacts[0].read_text()
    assert "\t" in content
    assert "AccountNumber\tAccountName" in content
    # Cash → asset code '1'.
    assert "1000\tCash\t1\t1200.00" in content


def test_lacerte_adapter_blocks_on_unmapped_type(tmp_path: Path):
    wtb = _wtb(
        [
            _row(
                number="1",
                name="Weird",
                account_type=AccountType.OTHER,
                adjusted="0",
            )
        ]
    )
    adapter = LacerteAdapter()
    blockers = adapter.validate(wtb)
    assert any(b.rule_id == "lacerte.unmapped_account_type" for b in blockers)


def test_quickbooks_iif_adapter_emits_iif_with_crlf(tmp_path: Path):
    adapter = QuickBooksIifAdapter()
    result = adapter.emit(_wtb(), tmp_path)
    raw = result.artifacts[0].read_bytes()
    assert b"\r\n" in raw
    assert b"!TRNS" in raw
    assert b"!SPL" in raw


def test_quickbooks_iif_refuses_when_no_adjustments(tmp_path: Path):
    wtb = _wtb(
        [
            _row(
                number="1000",
                name="Cash",
                account_type=AccountType.ASSET,
                adjusted="0",
                sum_aje="0",
            ),
        ]
    )
    adapter = QuickBooksIifAdapter()
    with pytest.raises(RefuseToEmit):
        adapter.emit(wtb, tmp_path)
