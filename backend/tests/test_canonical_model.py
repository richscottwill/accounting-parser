"""Property tests for the canonical financial model.

Correctness Property 2: ``parse_canonical_json(canonical_json(m))`` equals
                         ``m`` under the equivalence relation.
Correctness Property 3: ``canonical_json(m) == canonical_json(m)`` byte-identical.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import hypothesis.strategies as st
from hypothesis import HealthCheck, given, settings

from accounting_parser.model import (
    Account,
    BoundingBox,
    FixedAsset,
    JournalEntryAdjustment,
    JournalLeg,
    ParseResult,
    ReportLine,
    ReportSection,
    TaxFormField,
    WorkingTrialBalance,
    canonical_json,
    equals_under_equivalence,
    parse_canonical_json,
)
from accounting_parser.model.canonical import (
    AccountType,
    DepreciationMethod,
    EntryStatus,
    EntryType,
    NormalBalance,
    ReportType,
    SourceRef,
    WTBRow,
)


# ---------- Strategies ----------

UTC = timezone.utc

decimal_strategy = st.decimals(
    min_value=Decimal("-1000000"),
    max_value=Decimal("1000000"),
    allow_nan=False,
    allow_infinity=False,
    places=2,
)


@st.composite
def account_strategy(draw):
    name = draw(st.text(min_size=1, max_size=32, alphabet=st.characters(
        whitelist_categories=("L", "N"))))
    return Account(
        account_number=draw(st.text(min_size=1, max_size=16, alphabet=st.characters(
            whitelist_categories=("L", "N")))),
        account_name=name,
        account_type=draw(st.one_of(st.none(), st.sampled_from(AccountType))),
        normal_balance=draw(st.one_of(st.none(), st.sampled_from(NormalBalance))),
        category=draw(st.one_of(st.none(), st.text(min_size=1, max_size=16, alphabet=st.characters(
            whitelist_categories=("L", "N"))))),
        category_confidence=draw(st.one_of(
            st.none(),
            st.decimals(min_value=Decimal("0"), max_value=Decimal("1"), places=3),
        )),
    )


@st.composite
def report_line_strategy(draw):
    return ReportLine(
        line_id=draw(st.text(min_size=1, max_size=16, alphabet=st.characters(
            whitelist_categories=("L", "N")))),
        account=draw(account_strategy()),
        debit=draw(decimal_strategy),
        credit=draw(decimal_strategy),
        balance=draw(decimal_strategy),
    )


@st.composite
def report_section_strategy(draw):
    return ReportSection(
        section_id=draw(st.text(min_size=1, max_size=16, alphabet=st.characters(
            whitelist_categories=("L", "N")))),
        title=draw(st.text(min_size=1, max_size=32, alphabet=st.characters(
            whitelist_categories=("L", "N")))),
        lines=tuple(draw(st.lists(report_line_strategy(), max_size=5))),
    )


@st.composite
def fixed_asset_strategy(draw):
    return FixedAsset(
        asset_id=draw(st.text(min_size=1, max_size=16, alphabet=st.characters(
            whitelist_categories=("L", "N")))),
        description=draw(st.text(min_size=1, max_size=32, alphabet=st.characters(
            whitelist_categories=("L", "N", "Zs")))),
        class_life=draw(st.integers(min_value=3, max_value=39)),
        placed_in_service=draw(st.datetimes(
            min_value=datetime(2000, 1, 1), max_value=datetime(2030, 12, 31)
        ).map(lambda dt: dt.replace(tzinfo=UTC))),
        cost_basis=draw(st.decimals(min_value=Decimal("0"), max_value=Decimal("1000000"), places=2)),
        section_179=draw(st.decimals(min_value=Decimal("0"), max_value=Decimal("10000"), places=2)),
        bonus_rate=draw(st.decimals(min_value=Decimal("0"), max_value=Decimal("1"), places=4)),
        book_method=draw(st.sampled_from(DepreciationMethod)),
        tax_method=draw(st.sampled_from(DepreciationMethod)),
    )


@st.composite
def journal_leg_strategy(draw):
    # Legs must have either debit > 0 or credit > 0 but not both
    is_debit = draw(st.booleans())
    amt = draw(st.decimals(min_value=Decimal("0.01"), max_value=Decimal("10000"), places=2))
    return JournalLeg(
        account=draw(account_strategy()),
        debit=amt if is_debit else Decimal("0"),
        credit=Decimal("0") if is_debit else amt,
    )


@st.composite
def journal_entry_strategy(draw):
    return JournalEntryAdjustment(
        entry_id=draw(st.uuids()),
        entry_type=draw(st.sampled_from(EntryType)),
        description=draw(st.text(min_size=1, max_size=64, alphabet=st.characters(
            whitelist_categories=("L", "N", "Zs")))),
        legs=tuple(draw(st.lists(journal_leg_strategy(), min_size=2, max_size=4))),
        status=draw(st.sampled_from(EntryStatus)),
    )


@st.composite
def parse_result_strategy(draw):
    return ParseResult(
        document_id=draw(st.uuids()),
        report_type=draw(st.sampled_from(ReportType)),
        parser_version="test-0.1",
        parsed_at=draw(st.datetimes(
            min_value=datetime(2020, 1, 1), max_value=datetime(2030, 12, 31)
        ).map(lambda dt: dt.replace(tzinfo=UTC))),
        sections=tuple(draw(st.lists(report_section_strategy(), max_size=3))),
    )


# ---------- Property tests ----------


@given(parse_result_strategy())
@settings(max_examples=1000, deadline=None,
          suppress_health_check=[HealthCheck.filter_too_much])
def test_canonical_json_is_deterministic(m: ParseResult) -> None:
    """Correctness Property 3: pretty_print(m) == pretty_print(m) byte-identical."""
    a = canonical_json(m)
    b = canonical_json(m)
    assert a == b


@given(parse_result_strategy())
@settings(max_examples=1000, deadline=None,
          suppress_health_check=[HealthCheck.filter_too_much])
def test_canonical_json_round_trips(m: ParseResult) -> None:
    """Correctness Property 2: parse(json(m)) == m under equivalence relation."""
    js = canonical_json(m)
    parsed = parse_canonical_json(js, ParseResult)
    assert equals_under_equivalence(m, parsed), (
        f"round-trip failed:\n  original canonical: {canonical_json(m)[:200]}\n"
        f"  parsed canonical:   {canonical_json(parsed)[:200]}"
    )


def test_float_rejected() -> None:
    """Canonical model forbids float — Decimal only (Resolution 8)."""
    from decimal import Decimal

    import pytest

    # Construct with Decimal OK
    rl = ReportLine(
        line_id="L1",
        account=Account(account_number="1000", account_name="Cash"),
        debit=Decimal("100.00"),
    )
    # canonical_json with a float value buried inside raises
    class Sneaky:
        """Bypass Pydantic to prove the encoder rejects float."""
        pass

    from accounting_parser.model.pretty_printer import _encode  # type: ignore[attr-defined]
    with pytest.raises(TypeError, match="float is forbidden"):
        _encode(3.14)


def test_schema_version_required() -> None:
    """Every top-level model has schema_version and it defaults to 1."""
    acc = Account(account_number="1000", account_name="Cash")
    assert acc.schema_version == 1
