"""Ordered-rules classifier.

Every classification records the matching rule_id or override_id so we
have rule provenance per R8.6.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from accounting_parser.model.canonical import Account, AccountType


CLASSIFICATION_FLOOR: Decimal = Decimal("0.60")


@dataclass(frozen=True)
class Classification:
    category: str
    confidence: Decimal
    rule_id: str  # override:<id> | rule:<id> | "unclassified"


@dataclass(frozen=True)
class Override:
    """Per-Client Category override. Highest priority."""

    override_id: str
    account_number: str
    category: str
    # Overrides are treated as fully confident by definition.
    confidence: Decimal = Decimal("1.00")


@dataclass(frozen=True)
class NumberRangeRule:
    rule_id: str
    low: str
    high: str
    category: str
    confidence: Decimal = Decimal("0.85")

    def matches(self, account_number: str) -> bool:
        return self.low <= account_number <= self.high


@dataclass(frozen=True)
class NameRegexRule:
    rule_id: str
    pattern: str
    category: str
    confidence: Decimal = Decimal("0.75")
    _compiled: re.Pattern = field(init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_compiled", re.compile(self.pattern, re.IGNORECASE))

    def matches(self, account_name: str) -> bool:
        return self._compiled.search(account_name) is not None


# Source-system-native account type -> Category mapping. Lower confidence
# than number-range or name-regex because account_type on a foreign-system
# account is often crude (e.g., "Income" covers both Revenue and Other Income).
_TYPE_TO_CATEGORY: dict[AccountType, str] = {
    AccountType.ASSET: "Assets",
    AccountType.LIABILITY: "Liabilities",
    AccountType.EQUITY: "Equity",
    AccountType.REVENUE: "Revenue",
    AccountType.EXPENSE: "Operating Expenses",
    AccountType.GAIN: "Other Income",
    AccountType.LOSS: "Other Expenses",
}


@dataclass
class Classifier:
    """A classifier scoped to a single Client (overrides + rules)."""

    overrides: tuple[Override, ...] = ()
    number_rules: tuple[NumberRangeRule, ...] = ()
    name_rules: tuple[NameRegexRule, ...] = ()

    def classify(self, account: Account) -> Classification:
        # 1. Per-Client overrides
        for ov in self.overrides:
            if ov.account_number == account.account_number:
                return Classification(
                    category=ov.category,
                    confidence=ov.confidence,
                    rule_id=f"override:{ov.override_id}",
                )
        # 2. Source-system-native type
        if account.account_type is not None:
            native = _TYPE_TO_CATEGORY.get(account.account_type)
            if native is not None:
                # Lower confidence for native type so number/name rules can
                # win when they match.
                native_conf = Decimal("0.65")
                # Keep this as a candidate but also try 3 and 4.
                best_rule = ("rule:native_account_type", native, native_conf)
            else:
                best_rule = None
        else:
            best_rule = None
        # 3. Account-number range rules
        for nr in self.number_rules:
            if nr.matches(account.account_number):
                if best_rule is None or nr.confidence > best_rule[2]:
                    best_rule = (f"rule:{nr.rule_id}", nr.category, nr.confidence)
        # 4. Account-name regex rules
        for nm in self.name_rules:
            if nm.matches(account.account_name):
                if best_rule is None or nm.confidence > best_rule[2]:
                    best_rule = (f"rule:{nm.rule_id}", nm.category, nm.confidence)

        if best_rule is None or best_rule[2] < CLASSIFICATION_FLOOR:
            return Classification(
                category="Unclassified",
                confidence=best_rule[2] if best_rule else Decimal("0"),
                rule_id="unclassified",
            )
        rule_id, category, conf = best_rule
        return Classification(category=category, confidence=conf, rule_id=rule_id)


# Default starter rules for a generic SMB chart of accounts.
STARTER_NUMBER_RULES: tuple[NumberRangeRule, ...] = (
    NumberRangeRule("n_assets", "1000", "1999", "Assets"),
    NumberRangeRule("n_liabilities", "2000", "2999", "Liabilities"),
    NumberRangeRule("n_equity", "3000", "3999", "Equity"),
    NumberRangeRule("n_revenue", "4000", "4999", "Revenue"),
    NumberRangeRule("n_cogs", "5000", "5999", "Cost of Goods Sold"),
    NumberRangeRule("n_opex", "6000", "6999", "Operating Expenses"),
)

STARTER_NAME_RULES: tuple[NameRegexRule, ...] = (
    NameRegexRule("nm_cash", r"\bcash\b", "Cash", Decimal("0.95")),
    NameRegexRule("nm_ar", r"\baccounts?\s*receivable\b", "Accounts Receivable", Decimal("0.95")),
    NameRegexRule("nm_ap", r"\baccounts?\s*payable\b", "Accounts Payable", Decimal("0.95")),
    NameRegexRule("nm_inventory", r"\binventory\b", "Inventory"),
    NameRegexRule("nm_cogs", r"\bcost\s*of\s*(goods|sales|revenue)\b", "Cost of Goods Sold", Decimal("0.95")),
    NameRegexRule("nm_meals", r"\bmeals\b", "Meals & Entertainment", Decimal("0.90")),
    NameRegexRule("nm_rent", r"\brent\b", "Rent Expense", Decimal("0.90")),
    NameRegexRule("nm_salaries", r"\b(salaries|wages|payroll)\b", "Payroll Expense", Decimal("0.90")),
    NameRegexRule("nm_deprec", r"\bdepreciation\b", "Depreciation", Decimal("0.90")),
    NameRegexRule("nm_penalty", r"\b(fines?|penalt)", "Fines and Penalties", Decimal("0.85")),
)


def classify(account: Account) -> Classification:
    """Classify using the starter ruleset."""
    return Classifier(
        overrides=(),
        number_rules=STARTER_NUMBER_RULES,
        name_rules=STARTER_NAME_RULES,
    ).classify(account)
