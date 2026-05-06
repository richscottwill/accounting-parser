"""Classifier tests — ordered rules + override priority + Unclassified floor."""

from __future__ import annotations

from decimal import Decimal

from accounting_parser.classifier import (
    CLASSIFICATION_FLOOR,
    Classifier,
    NameRegexRule,
    NumberRangeRule,
    Override,
    classify,
)
from accounting_parser.classifier.engine import (
    STARTER_NAME_RULES,
    STARTER_NUMBER_RULES,
)
from accounting_parser.model.canonical import Account, AccountType


def test_override_wins() -> None:
    acc = Account(account_number="6200", account_name="Meals & Entertainment")
    cls = Classifier(
        overrides=(Override(override_id="O1", account_number="6200", category="Travel"),),
        number_rules=STARTER_NUMBER_RULES,
        name_rules=STARTER_NAME_RULES,
    )
    result = cls.classify(acc)
    assert result.category == "Travel"
    assert result.rule_id == "override:O1"
    assert result.confidence == Decimal("1.00")


def test_number_range_rule_matches() -> None:
    acc = Account(account_number="1000", account_name="Unknown")
    result = classify(acc)
    assert result.category == "Assets"
    assert result.rule_id == "rule:n_assets"


def test_name_regex_wins_over_number() -> None:
    acc = Account(account_number="6100", account_name="Rent Expense")
    result = classify(acc)
    # nm_rent is 0.90, number n_opex is 0.85 — name wins
    assert result.category == "Rent Expense"
    assert result.rule_id == "rule:nm_rent"


def test_ambiguous_account_routed_to_unclassified() -> None:
    acc = Account(account_number="9999", account_name="Deposit")
    result = classify(acc)
    # No number-range, no name-regex match -> unclassified
    assert result.category == "Unclassified"
    assert result.rule_id == "unclassified"


def test_native_account_type_boosts_when_no_other_match() -> None:
    acc = Account(account_number="9999", account_name="Random thing",
                  account_type=AccountType.LIABILITY)
    result = classify(acc)
    # Native type confidence is 0.65 which is above floor of 0.60
    assert result.category == "Liabilities"
    assert result.rule_id == "rule:native_account_type"


def test_confidence_below_floor_routes_unclassified() -> None:
    # Custom rule with sub-floor confidence
    acc = Account(account_number="7777", account_name="Suspense")
    cls = Classifier(
        overrides=(),
        number_rules=(),
        name_rules=(NameRegexRule("nm_suspense", r"suspense", "Suspense",
                                  Decimal("0.50")),),
    )
    result = cls.classify(acc)
    assert result.category == "Unclassified"
