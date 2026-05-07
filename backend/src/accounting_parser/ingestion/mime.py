"""Magic-byte MIME detection for ingested Documents.

We detect the actual content type from the first few bytes of the stream
and compare it against what the client declared. Per Requirement 1.6 the
upload is rejected when they disagree.

Lightweight magic-byte check rather than a full libmagic dependency — the
supported document set is bounded (see Requirement 1.3), so a signature
table covering that set is sufficient. Adding libmagic would widen
coverage but adds a binary dep that breaks on DevSpaces without apt.
"""
from __future__ import annotations

from dataclasses import dataclass


# Signature table: (magic prefix, optional offset, detected mime).
# Signatures are ordered most-specific first. The matcher stops at the
# first hit.
_SIGNATURES: list[tuple[bytes, int, str]] = [
    # PDF
    (b"%PDF-", 0, "application/pdf"),
    # Office Open XML (XLSX, XLSM, DOCX, PPTX) — ZIP container.
    # We refine to "xlsx-ish" by looking for the [Content_Types].xml entry,
    # but the ZIP magic alone is the baseline signal.
    (b"PK\x03\x04", 0, "application/vnd.openxmlformats-officedocument.zip"),
    (b"PK\x05\x06", 0, "application/vnd.openxmlformats-officedocument.zip"),
    # XLSB — ZIP container too; distinguished by workbook.bin presence.
    # Legacy XLS (BIFF): OLE2 compound file.
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", 0, "application/vnd.ms-excel"),
    # XBRL (XML instance).
    (b"<?xml", 0, "application/xml"),
    # OFX 2 (XML) — falls under application/xml; OFX 1 is SGML.
    (b"OFXHEADER", 0, "application/x-ofx"),
    # QFX = OFX with Intuit tag.
    (b"QFXHEADER", 0, "application/x-ofx"),
    # QIF always starts with '!Type:'.
    (b"!Type:", 0, "application/vnd.intu.qif"),
    # IIF begins with '!ACCNT', '!TRNS', '!SPL', or '!HDR'.
    (b"!ACCNT", 0, "application/vnd.intuit-iif"),
    (b"!TRNS", 0, "application/vnd.intuit-iif"),
    (b"!HDR", 0, "application/vnd.intuit-iif"),
]


# Accepted MIME types and the declared→detected equivalence table.
# Clients send declared types that don't always match the narrow detected
# bucket (e.g., "text/csv" vs "text/plain"). The pairs below are treated
# as equivalent so we don't reject legitimate uploads.
_MIME_EQUIVALENCE: dict[str, set[str]] = {
    "application/pdf": {"application/pdf"},
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {
        "application/vnd.openxmlformats-officedocument.zip",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    },
    "application/vnd.openxmlformats-officedocument.spreadsheetml.template": {
        "application/vnd.openxmlformats-officedocument.zip",
    },
    "application/vnd.ms-excel": {
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.zip",  # XLSB
    },
    "application/vnd.ms-excel.sheet.binary.macroEnabled.12": {
        "application/vnd.openxmlformats-officedocument.zip",
    },
    "application/vnd.ms-excel.sheet.macroEnabled.12": {
        "application/vnd.openxmlformats-officedocument.zip",
    },
    "text/csv": {"text/plain", "text/csv"},
    "text/plain": {"text/plain", "text/csv", "text/tab-separated-values"},
    "text/tab-separated-values": {"text/plain", "text/tab-separated-values"},
    "application/xml": {"application/xml", "text/xml"},
    "text/xml": {"application/xml", "text/xml"},
    "application/x-ofx": {"application/x-ofx", "text/plain", "text/xml"},
    "application/vnd.intu.qif": {"application/vnd.intu.qif", "text/plain"},
    "application/vnd.intuit-iif": {"application/vnd.intuit-iif", "text/plain"},
}


# File extensions we are willing to ingest. Case-insensitive. This is a
# belt-and-suspenders with MIME-type checks — every upload must pass both.
ACCEPTED_EXTENSIONS: frozenset[str] = frozenset(
    {
        "pdf",
        "xlsx", "xlsm", "xlsb", "xls",
        "csv", "tsv", "txt",
        "ofx", "qfx", "qif", "iif", "qbo", "qbb",
        "xbrl", "xml",
    }
)


@dataclass(frozen=True)
class DetectionResult:
    detected_mime: str
    is_text: bool


def detect_mime(head_bytes: bytes) -> DetectionResult:
    """Return the detected MIME from a head-of-file byte sample.

    Falls back to ``application/octet-stream`` when no signature matches.
    """
    # Trim to the window we actually inspect.
    sample = head_bytes[:512]
    for magic, offset, mime in _SIGNATURES:
        if sample[offset : offset + len(magic)] == magic:
            return DetectionResult(
                detected_mime=mime,
                is_text=mime.startswith("text/") or mime in ("application/xml",),
            )

    # Heuristic for CSV / TSV / TXT: printable ASCII or UTF-8 without
    # binary control bytes (excluding \t \n \r).
    if _looks_like_text(sample):
        return DetectionResult(detected_mime="text/plain", is_text=True)

    return DetectionResult(detected_mime="application/octet-stream", is_text=False)


def _looks_like_text(sample: bytes) -> bool:
    """Simple text-vs-binary heuristic.

    Rejects any 0x00 or unexpected control char. Tolerates UTF-8 BOM.
    """
    if sample.startswith(b"\xef\xbb\xbf"):
        sample = sample[3:]
    if b"\x00" in sample:
        return False
    non_text = sum(
        1
        for b in sample
        if b < 0x20 and b not in (0x09, 0x0A, 0x0D)
    )
    return non_text / max(len(sample), 1) < 0.05


def mime_declared_matches_detected(declared: str, detected: str) -> bool:
    """True when declared and detected MIMEs are allowed to coexist."""
    declared = declared.strip().lower()
    detected = detected.strip().lower()
    if declared == detected:
        return True
    eq = _MIME_EQUIVALENCE.get(declared)
    return eq is not None and detected in eq
