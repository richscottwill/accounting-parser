"""Rules-based account Category classifier.

Ordered-rules engine per R8.2:
    1. Per-Client overrides (highest priority)
    2. Source-system-native account type mapping
    3. Account-number range rules
    4. Account-name regex rules

Category confidence < 0.6 routes to "Unclassified".

At MVP the ML classifier layer is deferred (per design §3.4 resolution).
"""

from accounting_parser.classifier.engine import (
    CLASSIFICATION_FLOOR,
    Classification,
    Classifier,
    NameRegexRule,
    NumberRangeRule,
    Override,
    classify,
)

__all__ = [
    "Classifier",
    "Classification",
    "Override",
    "NumberRangeRule",
    "NameRegexRule",
    "classify",
    "CLASSIFICATION_FLOOR",
]
