"""AlertingAdapter tests."""

from __future__ import annotations

import httpx
import pytest

from accounting_parser.observability.alerting import (
    AlertmanagerAdapter,
    AlertSeverity,
    NullAlertingAdapter,
)


def test_null_adapter_records_fire():
    adapter = NullAlertingAdapter()
    adapter.fire(
        name="BackupFailed",
        severity=AlertSeverity.SEV_1,
        description="Nightly backup failed for 3 consecutive days",
        context={"last_success": "2026-05-07"},
    )
    assert len(adapter.alerts) == 1
    alert = adapter.alerts[0]
    assert alert["name"] == "BackupFailed"
    assert alert["severity"] == "sev_1"
    assert alert["context"]["last_success"] == "2026-05-07"


def test_alertmanager_adapter_posts_expected_payload():
    """Verify POST shape matches Alertmanager /api/v2/alerts contract."""
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.append(json.loads(request.content))
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    adapter = AlertmanagerAdapter(base_url="http://alertmanager:9093", client=client)

    adapter.fire(
        name="ParseSuccessRateLow",
        severity=AlertSeverity.SEV_2,
        description="Parse success rate dropped to 87%",
        context={"rate": "0.87", "window": "1h"},
    )

    assert len(captured) == 1
    payload = captured[0]
    assert len(payload) == 1
    alert = payload[0]
    assert alert["labels"]["alertname"] == "ParseSuccessRateLow"
    assert alert["labels"]["severity"] == "sev_2"
    assert alert["labels"]["service"] == "accounting-parser"
    assert alert["annotations"]["description"] == "Parse success rate dropped to 87%"
    assert alert["annotations"]["rate"] == "0.87"


def test_alertmanager_adapter_swallows_network_errors():
    """Alerting failure must not mask the underlying event."""

    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("alertmanager down")

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    adapter = AlertmanagerAdapter(base_url="http://x", client=client)

    # Should not raise.
    adapter.fire(
        name="Test",
        severity=AlertSeverity.SEV_3,
        description="down",
    )


@pytest.mark.parametrize(
    "sev",
    [AlertSeverity.SEV_1, AlertSeverity.SEV_2, AlertSeverity.SEV_3],
)
def test_severity_enum_values_are_stable(sev):
    """Labels land in Alertmanager routing rules — values can't change silently."""
    assert sev.value in {"sev_1", "sev_2", "sev_3"}
