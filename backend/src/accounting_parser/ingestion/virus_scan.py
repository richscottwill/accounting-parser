"""VirusScanner Protocol + implementations.

Runs a virus scan over uploaded bytes before they hit the document
table's ``uploaded`` state. The scanner runs AS PART OF ingestion —
it doesn't happen asynchronously post-upload, because a quarantined
file should never be visible to downstream parsers.

### Implementations

- ``ClamdVirusScanner``  — talks to the ClamAV clamd daemon running
  in the compose stack. Uses the ``clamd`` Python client.
- ``NullVirusScanner``   — always returns clean. Used in unit tests
  and when the firm has explicitly opted out (a configuration
  choice documented with prominent warnings; not our default).

Callers depend on the Protocol, not either implementation. Tests
inject ``NullVirusScanner``; production wires ``ClamdVirusScanner``
via the DI container.

### EICAR test

The EICAR test string is the industry-standard "we're testing that
virus scanning actually runs" pattern. ClamAV recognizes it as a
virus signature even though it's harmless text. Our smoke tests
(P1.6 compose validation) upload an EICAR file and assert the
scanner flags it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO, Protocol


class VirusScanner(Protocol):
    """Contract for any virus-scan backend."""

    def scan(self, stream: BinaryIO) -> ScanResult:
        """Scan the bytes in ``stream`` and return a result.

        The stream is consumed; callers must re-open or seek if they
        need the bytes after scanning. For most ingestion flows the
        scanner is called on a buffered copy held in memory, so the
        caller can stream the same bytes to storage after.

        MUST NOT raise on infected content — that's a successful
        scan that found something. Exceptions indicate scanner
        failure (service down, protocol error), which the caller
        maps to ``VirusScanError`` with reason ``scanner_unavailable``.
        """
        ...


@dataclass(frozen=True)
class ScanResult:
    """Outcome of a virus scan.

    ``is_clean == True`` means no signatures matched.
    ``is_clean == False`` implies ``signature`` is non-None and carries
    the matched virus name (e.g., ``Win.Test.EICAR_HDB-1``).
    """

    is_clean: bool
    signature: str | None = None
    scanner_version: str | None = None


class NullVirusScanner:
    """Always returns clean. Tests + opted-out deployments only.

    Deliberately does not implement any pattern matching. If you find
    yourself wanting "a scanner that matches test signatures but not
    real ones," use a ``FakeScanner`` test double instead — this
    class is the unambiguous "no scanning happens" marker.
    """

    def scan(self, stream: BinaryIO) -> ScanResult:
        # Consume the stream so callers see the same side effect as
        # with a real scanner (stream position advances to EOF).
        while stream.read(65536):
            pass
        return ScanResult(is_clean=True, scanner_version="null-0")


class ClamdVirusScanner:
    """Talks to a clamd daemon over TCP or unix socket.

    Lazy import of the ``clamd`` package so tests that never touch
    this class don't pull the dep into their path (``clamd`` is an
    optional dep; the installer pins it when deploying with ClamAV).
    """

    def __init__(self, *, host: str = "clamav", port: int = 3310) -> None:
        self.host = host
        self.port = port
        self._client: object | None = None

    def _get_client(self) -> object:
        if self._client is None:
            import clamd  # type: ignore[import-not-found]

            self._client = clamd.ClamdNetworkSocket(host=self.host, port=self.port)
        return self._client

    def scan(self, stream: BinaryIO) -> ScanResult:
        client = self._get_client()
        # clamd.instream returns {"stream": ("OK", None) } for clean,
        # {"stream": ("FOUND", signature) } for match.
        result = client.instream(stream)  # type: ignore[attr-defined]
        status, signature = result["stream"]
        if status == "OK":
            return ScanResult(is_clean=True, scanner_version="clamd")
        if status == "FOUND":
            return ScanResult(is_clean=False, signature=signature, scanner_version="clamd")
        # ERROR status: treat as scanner failure so the caller raises.
        raise RuntimeError(f"clamd scan returned unexpected status {status!r}: {signature}")
