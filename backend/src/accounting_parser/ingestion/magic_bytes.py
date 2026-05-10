"""Magic-byte MIME detection.

Goal: catch declared-vs-detected content-type mismatches at ingest
time. Prevents a malicious client from claiming a PDF but uploading
an executable — the parser-level validation would eventually catch
that but with a worse audit trail.

### Approach

Hand-rolled signatures for the content types we actually accept.
Using python-magic / libmagic would pull in a native dependency and
expose us to breaking changes in its mime-type taxonomy; with only
~8 formats to detect, a static lookup table is simpler and more
auditable.

If a firm adds a format type outside this table, the fallback is
``application/octet-stream`` and ``IngestionService`` rejects it as
``InvalidContentTypeError`` — false negatives fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MimeSignature:
    """A magic-byte pattern for one content type.

    ``offset`` is the starting byte index. Most signatures start at 0;
    OLE2 office formats use 0 too, but ZIP-based office files (xlsx)
    are detected by a header pattern plus a nested-file check we do
    separately (``_looks_like_xlsx``) because every zip starts with
    the same magic bytes.
    """

    content_type: str
    offset: int
    pattern: bytes


# Order matters: more specific signatures first. The first match wins.
_SIGNATURES: tuple[MimeSignature, ...] = (
    MimeSignature("application/pdf", 0, b"%PDF-"),
    MimeSignature("image/png", 0, b"\x89PNG\r\n\x1a\n"),
    MimeSignature("image/jpeg", 0, b"\xff\xd8\xff"),
    MimeSignature("image/tiff", 0, b"II*\x00"),
    MimeSignature("image/tiff", 0, b"MM\x00*"),
    # OLE2 Compound File (.xls, .doc, .msg, password-protected .docx)
    MimeSignature("application/x-ole-storage", 0, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
    # ZIP container — xlsx/docx/odt all start this way. Callers that
    # need to distinguish xlsx from generic-zip call ``_looks_like_xlsx``.
    MimeSignature("application/zip", 0, b"PK\x03\x04"),
    MimeSignature("application/zip", 0, b"PK\x05\x06"),
    MimeSignature("application/zip", 0, b"PK\x07\x08"),
)


# Common OFX / QIF / IIF files are plain text. We detect them by
# leading-line content, which is a weaker signal than magic bytes
# but sufficient given the declared-vs-detected cross-check in the
# service layer catches mismatches.
_TEXT_LEAD_PATTERNS: tuple[tuple[str, bytes], ...] = (
    ("application/x-ofx", b"OFXHEADER:"),
    ("application/x-ofx", b"<?xml"),  # OFX 2.x is XML
    ("application/x-qif", b"!Type:"),
    # IIF format starts with column headers like "!TRNS\tTRNSID..."
    ("application/x-iif", b"!TRNS"),
    ("application/x-xbrl", b"<?xml"),
    ("text/csv", b""),  # CSV has no stable prefix — fall through
)


ACCEPTED_MIMES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "application/vnd.ms-excel",  # .xls legacy
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
        "text/csv",
        "application/x-ofx",
        "application/x-qif",
        "application/x-iif",
        "application/x-xbrl",
    }
)


def detect_content_type(head: bytes) -> str:
    """Return the detected content-type for a leading byte sample.

    ``head`` should be at least 512 bytes when available (caller
    reads the first chunk of the upload before streaming the rest).
    Returns ``application/octet-stream`` when no pattern matches.
    """
    for sig in _SIGNATURES:
        if head[sig.offset : sig.offset + len(sig.pattern)] == sig.pattern:
            if sig.content_type == "application/zip" and _looks_like_xlsx(head):
                # Zip container with Office Open XML markers → xlsx.
                return (
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            return sig.content_type

    # Text-lead fallbacks (case-insensitive on the leading tag).
    lead_upper = head[:256].upper()
    for mime, lead_pat in _TEXT_LEAD_PATTERNS:
        if lead_pat and lead_upper.startswith(lead_pat.upper()):
            return mime

    return "application/octet-stream"


def _looks_like_xlsx(head: bytes) -> bool:
    """Heuristic: the zip central directory should mention xl/ or
    workbook.xml within the first chunk.

    For tiny workbooks the central directory is entirely in the head
    sample; larger ones have the local file headers within the first
    few KB and the pattern ``word/``, ``xl/``, or ``workbook.xml``
    appears in those headers.
    """
    sample = head[:4096]
    markers = (b"xl/", b"workbook.xml", b"[Content_Types].xml")
    return any(m in sample for m in markers)


def is_accepted(content_type: str) -> bool:
    """Return True if the content-type is on our allow-list."""
    return content_type in ACCEPTED_MIMES
