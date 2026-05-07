"""Aggregate metric emission (Requirement 15.2).

CloudWatch PutMetricData is the production path; a FakeMetrics collector
keeps tests deterministic + runnable without AWS.

Metrics per design §7.2:
- parse_success_rate per (source_system, report_type)
- classification_confidence_distribution (p50/p90/p99)
- validator_findings by severity
- workflow_success_rate by template + step
- export_success_rate by target_system
- ocr_spend (pages) per tenant

All dimensions use **hashed** tenant_id to prevent Tenant identification
via CloudWatch metric names or dimension values.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

import boto3

from accounting_parser.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass
class Metric:
    name: str
    value: float
    unit: str = "Count"
    dimensions: dict[str, str] = field(default_factory=dict)


class MetricsClient(Protocol):
    backend: str

    def emit(self, metric: Metric) -> None: ...


def hashed_tenant(tenant_id: str | bytes) -> str:
    """Stable short hash of the tenant UUID for use as a dimension."""
    if isinstance(tenant_id, bytes):
        s = tenant_id.decode("utf-8", errors="ignore")
    else:
        s = str(tenant_id)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


class CloudWatchMetrics:
    backend = "cloudwatch"

    def __init__(self, settings: Settings, namespace: str = "AccountingParser"):
        self.namespace = namespace
        kwargs: dict[str, Any] = {
            "region_name": settings.aws_region,
            "aws_access_key_id": settings.aws_access_key_id,
            "aws_secret_access_key": settings.aws_secret_access_key,
        }
        if settings.aws_endpoint_url:
            kwargs["endpoint_url"] = settings.aws_endpoint_url
        self._client = boto3.client("cloudwatch", **kwargs)

    def emit(self, metric: Metric) -> None:
        self._client.put_metric_data(
            Namespace=self.namespace,
            MetricData=[{
                "MetricName": metric.name,
                "Value": metric.value,
                "Unit": metric.unit,
                "Dimensions": [
                    {"Name": k, "Value": v} for k, v in metric.dimensions.items()
                ],
            }],
        )


class FakeMetrics:
    """Collects metrics in-process; inspect via ``.emitted``. Dev + CI."""

    backend = "fake"

    def __init__(self) -> None:
        self.emitted: list[Metric] = []

    def emit(self, metric: Metric) -> None:
        self.emitted.append(metric)


def get_metrics(settings: Settings | None = None) -> MetricsClient:
    settings = settings or get_settings()
    backend = getattr(settings, "metrics_backend", "fake")
    if backend == "cloudwatch":
        return CloudWatchMetrics(settings)
    return FakeMetrics()
