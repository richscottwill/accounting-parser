"""Malware scanner adapter.

Three backends:
- ``clamav``  — clamd daemon over the CLAMD protocol (production).
- ``eicar``   — in-process signature check for the EICAR test string
                (good enough for dev + CI without installing clamd).
- ``skip``    — no-op that marks every scan as ``clean``. Dev-only.

Selected via ``settings.malware_scanner_backend``. Switching backends
changes only which implementation runs; the contract and the audit-log
shape stay identical.
"""
from __future__ import annotations

import logging
import socket
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from accounting_parser.config import Settings, get_settings

logger = logging.getLogger(__name__)


class ScanResult(Enum):
    CLEAN = "clean"
    INFECTED = "infected"
    ERROR = "error"


@dataclass(frozen=True)
class ScanOutcome:
    result: ScanResult
    engine: str
    finding: str | None  # signature name or error message


class MalwareScanner(Protocol):
    engine: str

    def scan(self, content: bytes, *, filename: str) -> ScanOutcome: ...


# EICAR standard anti-malware test string — every compliant scanner flags
# this byte sequence as malware, so we use it for dev + CI smoke tests.
# https://en.wikipedia.org/wiki/EICAR_test_file
_EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class SkipScanner:
    """No-op scanner. Every input is reported clean. Dev-only."""

    engine = "skip"

    def scan(self, content: bytes, *, filename: str) -> ScanOutcome:
        return ScanOutcome(result=ScanResult.CLEAN, engine=self.engine, finding=None)


class EicarScanner:
    """In-process scanner that flags only the EICAR test string.

    Good enough for CI + local dev: proves the scan pathway runs + that
    infected uploads are quarantined, without installing clamd.
    """

    engine = "eicar-dev"

    def scan(self, content: bytes, *, filename: str) -> ScanOutcome:
        if _EICAR in content:
            return ScanOutcome(
                result=ScanResult.INFECTED,
                engine=self.engine,
                finding="Eicar-Test-Signature",
            )
        return ScanOutcome(result=ScanResult.CLEAN, engine=self.engine, finding=None)


class ClamAVScanner:
    """Talks to clamd via the INSTREAM command.

    Production default. Assumes clamd is reachable at
    ``settings.clamav_host:clamav_port`` as a sidecar.
    """

    engine = "clamav"

    def __init__(self, host: str, port: int, timeout_seconds: int = 30):
        self.host = host
        self.port = port
        self.timeout_seconds = timeout_seconds

    def scan(self, content: bytes, *, filename: str) -> ScanOutcome:
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout_seconds) as sock:
                sock.sendall(b"zINSTREAM\x00")
                chunk_size = 8192
                for i in range(0, len(content), chunk_size):
                    chunk = content[i : i + chunk_size]
                    sock.sendall(len(chunk).to_bytes(4, "big") + chunk)
                sock.sendall((0).to_bytes(4, "big"))  # zero-length terminator
                resp = b""
                while True:
                    buf = sock.recv(4096)
                    if not buf:
                        break
                    resp += buf
            text = resp.decode("utf-8", "replace").strip("\x00\n ")
            if text.endswith("OK"):
                return ScanOutcome(result=ScanResult.CLEAN, engine=self.engine, finding=None)
            if text.endswith("FOUND"):
                # Shape: "stream: <signature> FOUND"
                signature = text.replace("stream: ", "").removesuffix(" FOUND").strip()
                return ScanOutcome(
                    result=ScanResult.INFECTED, engine=self.engine, finding=signature
                )
            logger.warning("Unexpected clamd response", extra={"response": text})
            return ScanOutcome(result=ScanResult.ERROR, engine=self.engine, finding=text[:200])
        except (OSError, socket.timeout) as e:
            logger.exception("clamd scan failed")
            return ScanOutcome(result=ScanResult.ERROR, engine=self.engine, finding=str(e))


def get_scanner(settings: Settings | None = None) -> MalwareScanner:
    """Factory — returns the configured backend."""
    settings = settings or get_settings()
    backend = settings.malware_scanner_backend
    if backend == "clamav":
        return ClamAVScanner(settings.clamav_host, settings.clamav_port)
    if backend == "eicar":
        return EicarScanner()
    if backend == "skip":
        return SkipScanner()
    raise ValueError(f"Unknown malware_scanner_backend: {backend!r}")
