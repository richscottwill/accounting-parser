"""Observability subsystem (P2.2).

Three adapter layers, each with the same "protocol + prod impl +
noop for tests" shape that's now canon across the codebase:

- ``MetricsAdapter`` — counts, gauges, histograms. Prod:
  ``PrometheusMetricsAdapter`` scraped at ``/metrics``. Tests:
  ``NullMetricsAdapter``.
- ``LogSinkAdapter`` — structured log emission. Prod:
  ``LokiLogAdapter`` via stdout + promtail. Tests: ``NullLogSinkAdapter``.
- ``AlertingAdapter`` — raise SEV-1/2/3 alerts. Prod:
  ``AlertmanagerAdapter`` via webhook. Tests: ``NullAlertingAdapter``.

All three log to the audit chain when they fire — alerts and
critical log events are auditable operations.

### Redaction

Parent R27 mandates SSN/EIN/bank-account/monetary-pattern scrubbing
in logs. ``redaction.py`` implements the regex set; the log adapter
applies it before emission. Drops rather than hashes — a redacted
SSN isn't useful for debugging and hashed PII is still PII under the
IRS's reading of Pub 4557.
"""

from accounting_parser.observability.alerting import (
    AlertingAdapter,
    AlertmanagerAdapter,
    AlertSeverity,
    NullAlertingAdapter,
)
from accounting_parser.observability.logging import (
    LogSinkAdapter,
    LokiLogAdapter,
    NullLogSinkAdapter,
    configure_structured_logging,
)
from accounting_parser.observability.metrics import (
    MetricsAdapter,
    NullMetricsAdapter,
    PrometheusMetricsAdapter,
)
from accounting_parser.observability.redaction import redact_message

__all__ = [
    "AlertSeverity",
    "AlertingAdapter",
    "AlertmanagerAdapter",
    "LogSinkAdapter",
    "LokiLogAdapter",
    "MetricsAdapter",
    "NullAlertingAdapter",
    "NullLogSinkAdapter",
    "NullMetricsAdapter",
    "PrometheusMetricsAdapter",
    "configure_structured_logging",
    "redact_message",
]
