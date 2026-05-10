"""Log redaction.

Parent R27 requires every log line to strip SSN, EIN, bank-account,
and monetary-pattern content before emission. Self-hosted builds on
this (the logs leave the container via promtail → Loki, which is
still on the firm's host, but the firm's operators may screenshot or
share snippets; redaction prevents accidental PII exposure).

### Patterns

- SSN: ``XXX-XX-XXXX`` or ``XXXXXXXXX`` in a 9-digit run.
- EIN: ``XX-XXXXXXX``.
- Bank account: any 7-to-17 digit run flanked by word boundaries —
  broad enough to catch typical checking + savings lengths while
  not tagging every tracking number.
- Monetary pattern: ``$N[,NNN]+(.NN)?`` — we drop the whole pattern
  rather than just the sign because monetary values in error context
  are usually more diagnostic harm than help.

We *drop* rather than hash. Parent R27 explicitly says drop fields;
hashed PII is still PII for IRS Pub 4557 compliance purposes.
"""

from __future__ import annotations

import re

_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    # SSN dashed form first (more specific) then bare 9-digit.
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    (re.compile(r"\b\d{2}-\d{7}\b"), "[REDACTED_EIN]"),
    (re.compile(r"\b\d{9}\b"), "[REDACTED_9DIGIT]"),
    # Bank account 7-17 digits (loose end of the range).
    (re.compile(r"\b\d{7,17}\b"), "[REDACTED_ACCOUNT]"),
    # Monetary patterns: $12,345.67 or $1234 or $1,234 variants.
    (
        re.compile(r"\$\s?\d{1,3}(,\d{3})+(\.\d{2})?\b"),
        "[REDACTED_MONEY]",
    ),
    (re.compile(r"\$\s?\d+(\.\d{2})?\b"), "[REDACTED_MONEY]"),
)


def redact_message(message: str) -> str:
    """Return ``message`` with all redaction patterns applied.

    Idempotent: calling redact twice is safe (once replaced, the
    tokens match no pattern).
    """
    out = message
    for pattern, replacement in _PATTERNS:
        out = pattern.sub(replacement, out)
    return out
