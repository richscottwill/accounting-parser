"""Virus scanner contract tests."""

from __future__ import annotations

import io

from accounting_parser.ingestion.virus_scan import NullVirusScanner, ScanResult


def test_null_scanner_always_clean():
    s = NullVirusScanner()
    result = s.scan(io.BytesIO(b"anything"))
    assert isinstance(result, ScanResult)
    assert result.is_clean is True
    assert result.signature is None


def test_null_scanner_consumes_stream():
    """Null scanner consumes the stream so the caller observes EOF.

    Real scanners necessarily read to EOF; tests that rely on the
    post-scan stream position should match that expectation. Our
    ingestion service seeks the buffer back to 0 before using, but
    defensive test here in case a future caller doesn't.
    """
    stream = io.BytesIO(b"hello-world")
    NullVirusScanner().scan(stream)
    # After scan, read() should yield empty (stream at EOF).
    assert stream.read() == b""
