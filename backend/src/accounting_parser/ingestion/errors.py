"""IngestionService exceptions.

Route handlers catch ``IngestionError`` (the base class) and map
each subclass to a specific HTTP response:

- ``SizeLimitExceededError``    → 413 Payload Too Large
- ``InvalidContentTypeError``   → 415 Unsupported Media Type
- ``DuplicateDocumentError``    → 409 Conflict (response body
  includes the original document_id)
- ``VirusScanError``            → 422 Unprocessable Entity (the
  document is quarantined; state=``quarantined``)

All errors carry a short stable ``reason_code`` so downstream tools
(audit trail queries, UI copy) can branch on machine-readable values
without pattern-matching on prose.
"""

from __future__ import annotations

from uuid import UUID


class IngestionError(RuntimeError):
    """Base class for ingestion failures."""

    reason_code: str = "ingestion_error"


class SizeLimitExceededError(IngestionError):
    """Upload exceeded the configured byte-size limit."""

    reason_code = "size_limit_exceeded"

    def __init__(self, *, byte_size: int, limit: int) -> None:
        super().__init__(f"upload size {byte_size} bytes exceeds limit of {limit} bytes")
        self.byte_size = byte_size
        self.limit = limit


class InvalidContentTypeError(IngestionError):
    """Declared content-type disagrees with magic-byte detection.

    Attack vector: a client declares content-type ``application/pdf``
    but uploads an executable. The magic-byte check catches this and
    rejects before the blob ever reaches the parser.
    """

    reason_code = "invalid_content_type"

    def __init__(self, *, declared: str, detected: str) -> None:
        super().__init__(f"declared content-type {declared!r} does not match detected {detected!r}")
        self.declared = declared
        self.detected = detected


class DuplicateDocumentError(IngestionError):
    """A document with the same sha256 was already ingested for this Client.

    The constraint ``document_dedup_unique`` (tenant_id, client_id,
    sha256) raises this. We surface the original document's id so
    the UI can link back to it.
    """

    reason_code = "duplicate_document"

    def __init__(self, *, existing_document_id: UUID) -> None:
        super().__init__(f"document with the same sha256 already exists: {existing_document_id}")
        self.existing_document_id = existing_document_id


class VirusScanError(IngestionError):
    """The virus scanner flagged the upload.

    The service writes the document with ``ingest_state='quarantined'``
    and returns; the bytes remain in a quarantine prefix so incident
    response can inspect them out-of-band. The originating user sees
    a generic 422.
    """

    reason_code = "virus_detected"

    def __init__(self, *, signature: str) -> None:
        super().__init__(f"virus detected: {signature}")
        self.signature = signature


class PasswordProtectedError(IngestionError):
    """The uploaded file is password-protected (PDF / XLSX).

    Detected by a format-specific probe. We reject at ingest because
    parsing password-protected files is a deliberate non-goal —
    we'd either need to prompt the user for the passphrase (out of
    scope) or fail later at parse time (worse UX).
    """

    reason_code = "password_protected"

    def __init__(self, *, format_hint: str) -> None:
        super().__init__(f"file appears to be password-protected ({format_hint})")
        self.format_hint = format_hint
