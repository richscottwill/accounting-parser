"""MetricsAdapter tests."""

from __future__ import annotations

import pytest

from accounting_parser.observability.metrics import NullMetricsAdapter, PrometheusMetricsAdapter


def test_null_adapter_records_counter_calls():
    adapter = NullMetricsAdapter()
    adapter.inc_counter("parse_result_total", labels={"source_system": "qbo", "status": "ok"})
    assert adapter.counters[0][0] == "parse_result_total"
    assert adapter.counters[0][1] == {"source_system": "qbo", "status": "ok"}
    assert adapter.counters[0][2] == 1.0


def test_null_adapter_records_gauge_and_histogram():
    adapter = NullMetricsAdapter()
    adapter.set_gauge("disk_free_bytes", 1024 * 1024 * 1024)
    adapter.observe_histogram("classification_confidence", 0.87, labels={"source_system": "xero"})
    assert adapter.gauges == [("disk_free_bytes", 1024 * 1024 * 1024, {})]
    assert adapter.histograms[0][0] == "classification_confidence"
    assert adapter.histograms[0][1] == 0.87


def test_prometheus_adapter_registers_expected_metrics():
    """Unknown metric names raise at call site — drift fails loud."""
    adapter = PrometheusMetricsAdapter()
    # Known metric works.
    adapter.inc_counter("parse_result_total", labels={"source_system": "qbo", "status": "ok"})
    # Unknown metric raises.
    with pytest.raises(KeyError):
        adapter.inc_counter("not_registered", labels={"x": "y"})


def test_prometheus_expose_metrics_returns_bytes_with_known_counter():
    adapter = PrometheusMetricsAdapter()
    adapter.inc_counter("parse_result_total", labels={"source_system": "qbo", "status": "ok"})
    body = adapter.expose_metrics()
    assert isinstance(body, bytes)
    assert b"parse_result_total" in body


def test_prometheus_histogram_rejects_unknown_name():
    adapter = PrometheusMetricsAdapter()
    with pytest.raises(KeyError):
        adapter.observe_histogram("unknown_hist", 0.5)


def test_prometheus_gauge_rejects_unknown_name():
    adapter = PrometheusMetricsAdapter()
    with pytest.raises(KeyError):
        adapter.set_gauge("unknown_gauge", 42)
