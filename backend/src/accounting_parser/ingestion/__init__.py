"""Document ingestion subsystem.

Entry point: ``IngestionService``. Orchestrates:

1. Size limit enforcement (100 MB default per R22.1 / parent spec).
2. MIME-type detection via magic bytes (declared-vs-detected check).
3. SHA-256 digest computation (single pass over the stream).
4. Per-(Firm, Client) dedup via the ``document_dedup_unique``
   constraint.
5. Virus scan via the injected ``VirusScanner`` (ClamAV in production,
   ``NullScanner`` in tests).
6. Upload to the injected ``DocumentStoreAdapter`` (MinIO by default).
7. Persist ``document`` row with ``ingest_state = 'uploaded'``.
8. Append audit event ``document.ingested`` (or ``document.rejected``
   with a reason code).

The service never runs parsers itself — parsing is a downstream
workflow step (Task 7 source-detector, P1.4 workflow engine). This
module's job ends when the document is persisted + scanned + uploaded.
"""

from accounting_parser.ingestion.errors import (
    DuplicateDocumentError,
    IngestionError,
    InvalidContentTypeError,
    SizeLimitExceededError,
    VirusScanError,
)
from accounting_parser.ingestion.service import IngestionResult, IngestionService

__all__ = [
    "DuplicateDocumentError",
    "IngestionError",
    "IngestionResult",
    "IngestionService",
    "InvalidContentTypeError",
    "SizeLimitExceededError",
    "VirusScanError",
]
