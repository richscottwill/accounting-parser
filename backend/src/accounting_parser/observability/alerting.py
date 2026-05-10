"""AlertingAdapter — SEV-1/2/3 escalation.

Production: ``AlertmanagerAdapter`` POSTs to Alertmanager's webhook
receiver. Tests: ``NullAlertingAdapter`` records calls.

### SEV tiers (matches fork design §9.3)

- SEV_1 — service down, hash-chain verification failure, backup
  failed 3 days running. Emails Firm_Administrator + in-app banner.
- SEV_2 — parse success rate < 95% over 1 hour, export adapter
  smoke-test failure, disk < 10% free. Emails Firm_Administrator.
- SEV_3 — slow queries, elevated validator findings, backup job
  took longer than usual. Dashboard only, no email.

Mapping sev → channel lives in the Alertmanager route config, not
here. The adapter's job is to post the alert event; routing rules
ship with the compose stack.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol

import httpx


class AlertSeverity(str, Enum):
    SEV_1 = "sev_1"
    SEV_2 = "sev_2"
    SEV_3 = "sev_3"


@dataclass(frozen=True)
class _Alert:
    """Shape Alertmanager expects on /api/v2/alerts."""

    labels: dict[str, str]
    annotations: dict[str, str]
    starts_at: datetime


class AlertingAdapter(Protocol):
    provider: str

    def fire(
        self,
        *,
        name: str,
        severity: AlertSeverity,
        description: str,
        context: dict[str, Any] | None = None,
    ) -> None: ...


class NullAlertingAdapter(AlertingAdapter):
    """Records every fire() call in memory."""

    provider: str = "null"

    def __init__(self) -> None:
        self.alerts: list[dict[str, Any]] = []

    def fire(
        self,
        *,
        name: str,
        severity: AlertSeverity,
        description: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.alerts.append(
            {
                "name": name,
                "severity": severity.value,
                "description": description,
                "context": dict(context or {}),
            }
        )


class AlertmanagerAdapter(AlertingAdapter):
    """POSTs alerts to Alertmanager's REST API."""

    provider: str = "alertmanager"

    def __init__(self, *, base_url: str, client: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=httpx.Timeout(5.0))
        self._owns_client = client is None
        self._logger = logging.getLogger(__name__)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def fire(
        self,
        *,
        name: str,
        severity: AlertSeverity,
        description: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        labels = {
            "alertname": name,
            "severity": severity.value,
            "service": "accounting-parser",
        }
        annotations = {
            "description": description,
            **{k: str(v) for k, v in (context or {}).items()},
        }
        payload = [
            {
                "labels": labels,
                "annotations": annotations,
                "startsAt": datetime.now(UTC).isoformat(),
            }
        ]
        try:
            response = self._client.post(f"{self.base_url}/api/v2/alerts", json=payload)
            response.raise_for_status()
        except Exception as e:  # noqa: BLE001
            # Don't propagate — alerting failure must not mask the
            # underlying event. Log for ops.
            self._logger.error(
                "alertmanager_post_failed",
                extra={
                    "alert_name": name,
                    "severity": severity.value,
                    "error": str(e),
                },
            )
