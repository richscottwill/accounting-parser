"""MetricsAdapter — counters, gauges, histograms.

Production: ``PrometheusMetricsAdapter`` registers a
``prometheus_client.CollectorRegistry`` and exposes ``/metrics``.
Tests: ``NullMetricsAdapter`` records calls in memory for assertion.

### Named metrics (matches parent §7.2)

- ``parse_success_rate`` — per-Source_System histogram
- ``classification_confidence`` — distribution
- ``validator_findings_total`` — counter by finding type
- ``workflow_completion_total`` — counter by template_id + state
- ``export_success_total`` — counter by target
- ``ocr_pages_total`` — counter by provider + gate_triggered

Metric names are registered at adapter construction so drift
between call sites and registration surfaces at startup, not at
scrape time.
"""

from __future__ import annotations

from typing import Any, Protocol


class MetricsAdapter(Protocol):
    """Contract every metrics backend satisfies."""

    provider: str

    def inc_counter(
        self,
        name: str,
        *,
        labels: dict[str, str] | None = None,
        value: float = 1.0,
    ) -> None: ...

    def set_gauge(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, str] | None = None,
    ) -> None: ...

    def observe_histogram(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, str] | None = None,
    ) -> None: ...


class NullMetricsAdapter(MetricsAdapter):
    """Records every call in memory. Never exports anywhere.

    Tests use the recorded calls to assert "did the pipeline emit
    the metric it was supposed to?" without running Prometheus.
    """

    provider: str = "null"

    def __init__(self) -> None:
        self.counters: list[tuple[str, dict[str, str], float]] = []
        self.gauges: list[tuple[str, float, dict[str, str]]] = []
        self.histograms: list[tuple[str, float, dict[str, str]]] = []

    def inc_counter(
        self,
        name: str,
        *,
        labels: dict[str, str] | None = None,
        value: float = 1.0,
    ) -> None:
        self.counters.append((name, dict(labels or {}), value))

    def set_gauge(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, str] | None = None,
    ) -> None:
        self.gauges.append((name, value, dict(labels or {})))

    def observe_histogram(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, str] | None = None,
    ) -> None:
        self.histograms.append((name, value, dict(labels or {})))


class PrometheusMetricsAdapter(MetricsAdapter):
    """prometheus_client-backed adapter.

    Lazily imports ``prometheus_client`` so environments without it
    (test / CI) can use the null adapter without pulling the dep.
    Constructor registers known metrics up-front; unknown names
    passed to inc/set/observe raise — drift fails loud.
    """

    provider: str = "prometheus"

    def __init__(self) -> None:
        from prometheus_client import (  # type: ignore[import-not-found]
            CollectorRegistry,
            Counter,
            Gauge,
            Histogram,
        )

        self.registry = CollectorRegistry()
        self._counters: dict[str, Any] = {}
        self._gauges: dict[str, Any] = {}
        self._histograms: dict[str, Any] = {}

        # Register known metrics. Add new ones here and at their
        # call site in a single commit so drift doesn't accumulate.
        self._counters["parse_result_total"] = Counter(
            "parse_result_total",
            "Parse attempts by source_system and status",
            ["source_system", "status"],
            registry=self.registry,
        )
        self._counters["validator_findings_total"] = Counter(
            "validator_findings_total",
            "Validator findings emitted",
            ["report_type", "severity"],
            registry=self.registry,
        )
        self._counters["workflow_completion_total"] = Counter(
            "workflow_completion_total",
            "Workflow runs by template and final state",
            ["template_id", "state"],
            registry=self.registry,
        )
        self._counters["export_attempt_total"] = Counter(
            "export_attempt_total",
            "Export attempts by target and outcome",
            ["target", "outcome"],
            registry=self.registry,
        )
        self._counters["ocr_pages_total"] = Counter(
            "ocr_pages_total",
            "OCR pages processed by provider and gate outcome",
            ["provider", "gate_triggered"],
            registry=self.registry,
        )
        self._histograms["classification_confidence"] = Histogram(
            "classification_confidence",
            "Per-account classification confidence scores",
            ["source_system"],
            registry=self.registry,
        )
        self._gauges["disk_free_bytes"] = Gauge(
            "disk_free_bytes",
            "Host filesystem free bytes at /var/lib/accounting-parser",
            registry=self.registry,
        )
        self._gauges["backup_age_seconds"] = Gauge(
            "backup_age_seconds",
            "Seconds since last successful backup",
            registry=self.registry,
        )

    def inc_counter(
        self,
        name: str,
        *,
        labels: dict[str, str] | None = None,
        value: float = 1.0,
    ) -> None:
        counter = self._counters.get(name)
        if counter is None:
            raise KeyError(f"unregistered counter {name!r}")
        if labels:
            counter.labels(**labels).inc(value)
        else:
            counter.inc(value)

    def set_gauge(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, str] | None = None,
    ) -> None:
        gauge = self._gauges.get(name)
        if gauge is None:
            raise KeyError(f"unregistered gauge {name!r}")
        if labels:
            gauge.labels(**labels).set(value)
        else:
            gauge.set(value)

    def observe_histogram(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, str] | None = None,
    ) -> None:
        hist = self._histograms.get(name)
        if hist is None:
            raise KeyError(f"unregistered histogram {name!r}")
        if labels:
            hist.labels(**labels).observe(value)
        else:
            hist.observe(value)

    def expose_metrics(self) -> bytes:
        """Return the /metrics text body."""
        from prometheus_client import generate_latest  # type: ignore[import-not-found]

        return generate_latest(self.registry)
