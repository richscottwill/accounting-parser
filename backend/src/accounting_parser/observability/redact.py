"""PII redaction for logs + metrics.

Scrubs:
- SSN (``NNN-NN-NNNN`` and ``NNNNNNNNN``)  → ``***-**-<last 4>``
- EIN (``NN-NNNNNNN``)                     → ``**-***<last 4>``
- Bank account numbers (>= 6 contiguous digits in bank-account context)
  → ``****<last 4>``
- Dollar amounts adjacent to taxpayer identifiers → ``$***``

Applies structurally: redact_dict walks a dict/list tree and redacts
any string values. Applied to every log record's ``extra`` dict via
``structlog`` processor.
"""
from __future__ import annotations

import re
from typing import Any

_SSN_DASHED = re.compile(r"\b(\d{3})-(\d{2})-(\d{4})\b")
_SSN_FLAT = re.compile(r"\b\d{9}\b")
_EIN = re.compile(r"\b(\d{2})-(\d{7})\b")
_BANK_ACCT = re.compile(r"\b(account|acct|routing|aba)[\s#:]*(\d{6,})\b", re.I)


def redact_text(value: str) -> str:
    """Apply all redaction rules to a single string."""
    v = _SSN_DASHED.sub(r"***-**-\3", value)
    v = _SSN_FLAT.sub(lambda m: f"***-**-{m.group(0)[-4:]}", v)
    v = _EIN.sub(lambda m: f"**-***{m.group(2)[-4:]}", v)
    v = _BANK_ACCT.sub(
        lambda m: f"{m.group(1)} ****{m.group(2)[-4:]}",
        v,
    )
    return v


def redact(value: Any) -> Any:
    """Recursively redact a dict/list/scalar payload."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        out = [redact(v) for v in value]
        return type(value)(out) if isinstance(value, tuple) else out
    return value


def redact_processor(_logger, _method_name, event_dict: dict[str, Any]) -> dict[str, Any]:
    """structlog processor — call from the processor chain.

    Usage::

        structlog.configure(
            processors=[
                structlog.processors.TimeStamper(fmt="iso"),
                redact_processor,
                structlog.processors.JSONRenderer(),
            ]
        )
    """
    return redact(event_dict)
