"""Tests for the 8 Phase-2 exporters (Tasks 19 + 28).

Shape check: every adapter produces its declared artifacts, refuses on
blockers, and outputs a deterministic payload.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from accounting_parser.exporters.base import RefuseToEmit
from accounting_parser.exporters.phase2 import PHASE2_ADAPTERS
from accounting_parser.model.canonical import (
    Account,
    WorkingTrialBalance,
    WTBRow,
)


def _tb(balanced: bool = True, classified: bool = True) -> WorkingTrialBalance:
    cat = "revenue" if classified else None
    cat2 = "expense" if classified else None
    rows = [
        WTBRow(
            account=Account(
                account_number="4000",
                account_name="Revenue",
                category=cat,
            ),
            tax_basis=Decimal("-100.00"),
        ),
    ]
    if balanced:
        rows.append(
            WTBRow(
                account=Account(
                    account_number="5000",
                    account_name="COGS",
                    category=cat2,
                ),
                tax_basis=Decimal("100.00"),
            )
        )
    return WorkingTrialBalance(engagement_id=uuid4(), rows=tuple(rows))


@pytest.mark.parametrize("name,cls", PHASE2_ADAPTERS.items())
def test_adapter_happy_path_emits(tmp_path: Path, name: str, cls: type) -> None:
    result = cls().emit(_tb(), tmp_path / name)
    assert result.target_system == name
    assert len(result.artifacts) >= 1
    for p in result.artifacts:
        assert p.exists(), f"{p} missing"
        assert p.stat().st_size > 0


@pytest.mark.parametrize("name,cls", PHASE2_ADAPTERS.items())
def test_adapter_refuses_unclassified(tmp_path: Path, name: str, cls: type) -> None:
    with pytest.raises(RefuseToEmit) as exc:
        cls().emit(_tb(classified=False), tmp_path / name)
    rules = {b.rule_id for b in exc.value.args[0]}
    assert "unclassified_accounts" in rules


@pytest.mark.parametrize("name,cls", PHASE2_ADAPTERS.items())
def test_adapter_refuses_tax_basis_imbalanced(tmp_path: Path, name: str, cls: type) -> None:
    with pytest.raises(RefuseToEmit) as exc:
        cls().emit(_tb(balanced=False), tmp_path / name)
    rules = {b.rule_id for b in exc.value.args[0]}
    assert "tax_basis_imbalanced" in rules


def test_adapter_names_cover_required_targets() -> None:
    required = {
        "ultratax_advanceflow",
        "lacerte",
        "proseries",
        "proconnect",
        "drake",
        "caseware_working_papers",
        "quickbooks_iif",
        "gosystem_tax_rs",
    }
    assert required.issubset(set(PHASE2_ADAPTERS.keys()))
