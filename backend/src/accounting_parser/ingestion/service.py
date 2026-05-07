"""Ingestion orchestration — the single choke point every uploaded
Document passes through.

Flow (matches Requirement 1):
1. Authenticated session → tenant context is already pinned by the
   auth middleware; this service assumes an RLS-scoped Session.
2. Validate size ≤ configured ceiling (default 100 MB).
3. Detect MIME via magic bytes; reject on declared vs detected mismatch.
4. Malware-scan bytes; quarantine on hit, reject on engine error.
5. Compute SHA-256.
6. Dedup-by-hash on ``(tenant_id, client_id, sha256)``; reject with
   structured error referencing the original Document on hit.
7. Write bytes to per-Tenant storage with per-Tenant KMS CMK.
8. Insert Document row with ``ingest_state=received``.
9. Emit audit log entry.
10. Return the Document identifier.

Every branch that rejects or quarantines emits an audit entry with
a specific ``reason_code`` so support + Firm compliance can reconstruct
what happened.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from accounting_parser.auth.audit import emit_audit_event
from accounting_parser.config import Settings, get_settings
from accounting_parser.ingestion.mime import (
    ACCEPTED_EXTENSIONS,
    detect_mime,
    mime_declared_matches_detected,
)
from accounting_parser.ingestion.scanner import (
    MalwareScanner,
    ScanResult,
    get_scanner,
)
from accounting_parser.ingestion.storage import DocumentStorage, get_storage

logger = logging.getLogger(__name__)


# -- Errors --------------------------------------------------------------


class IngestionError(Exception):
    """Structured ingestion failure. ``reason_code`` is stable for clients."""

    def __init__(self, reason_code: str, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message
        self.status_code = status_code


class DuplicateDocumentError(IngestionError):
    def __init__(self, original_id: UUID):
        super().__init__(
            reason_code="duplicate_document",
            message=f"Duplicate of document {original_id}",
            status_code=409,
        )
        self.original_id = original_id


# -- Result --------------------------------------------------------------


@dataclass
class IngestResult:
    document_id: UUID
    sha256_hex: str
    storage_key: str
    detected_mime: str
    size_bytes: int
    quarantined: bool
    scan_engine: str
    ingest_state: str


# -- Service -------------------------------------------------------------


class IngestionService:
    """Orchestrate the 10-step ingestion flow."""

    def __init__(
        self,
        *,
        session: Session,
        storage: DocumentStorage | None = None,
        scanner: MalwareScanner | None = None,
        settings: Settings | None = None,
    ):
        self.session = session
        self.settings = settings or get_settings()
        self.storage = storage or get_storage(self.settings)
        self.scanner = scanner or get_scanner(self.settings)

    def upload(
        self,
        *,
        tenant_id: UUID,
        firm_id: UUID,
        client_id: UUID,
        engagement_id: UUID,
        uploader_user_id: UUID,
        filename: str,
        declared_mime: str,
        content: bytes,
        pbc_request_id: UUID | None = None,
    ) -> IngestResult:
        """Run the ingestion pipeline, persist, return the receipt."""
        # Step 2 — size ceiling.
        size_limit = self.settings.max_upload_bytes
        size = len(content)
        if size == 0:
            self._reject(tenant_id, uploader_user_id, filename, "empty_upload")
            raise IngestionError("empty_upload", "Zero-byte upload")
        if size > size_limit:
            self._reject(
                tenant_id, uploader_user_id, filename, "size_exceeded",
                extra={"size_bytes": size, "limit_bytes": size_limit},
            )
            raise IngestionError(
                "size_exceeded",
                f"File is {size} bytes; limit is {size_limit}.",
                status_code=413,
            )

        # Step 2b — extension allow-list.
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ACCEPTED_EXTENSIONS:
            self._reject(
                tenant_id, uploader_user_id, filename,
                "unsupported_extension", extra={"extension": ext},
            )
            raise IngestionError(
                "unsupported_extension",
                f"Extension {ext!r} not supported. Accepted: "
                + ", ".join(sorted(ACCEPTED_EXTENSIONS)),
            )

        # Step 3 — magic-byte MIME detection and declared-vs-detected check.
        detection = detect_mime(content[:512])
        if not mime_declared_matches_detected(declared_mime, detection.detected_mime):
            self._reject(
                tenant_id, uploader_user_id, filename, "mime_mismatch",
                extra={
                    "declared_mime": declared_mime,
                    "detected_mime": detection.detected_mime,
                },
            )
            raise IngestionError(
                "mime_mismatch",
                f"Declared {declared_mime!r} but detected {detection.detected_mime!r}.",
            )

        # Step 4 — malware scan.
        scan_outcome = self.scanner.scan(content, filename=filename)
        if scan_outcome.result == ScanResult.ERROR:
            self._reject(
                tenant_id, uploader_user_id, filename, "scan_error",
                extra={"scanner_error": scan_outcome.finding},
            )
            raise IngestionError(
                "scan_error",
                f"Malware scanner error: {scan_outcome.finding}",
            )
        quarantined = scan_outcome.result == ScanResult.INFECTED

        # Step 5 — SHA-256.
        digest = hashlib.sha256(content).digest()
        digest_hex = digest.hex()

        # Step 6 — dedup.
        if not quarantined:
            dup = self.session.execute(
                text(
                    """
                    SELECT id FROM document
                    WHERE tenant_id = :tid AND client_id = :cid AND sha256 = :sha
                    LIMIT 1
                    """
                ),
                {"tid": str(tenant_id), "cid": str(client_id), "sha": digest},
            ).first()
            if dup:
                self._reject(
                    tenant_id, uploader_user_id, filename, "duplicate_document",
                    extra={"original_document_id": str(dup[0])},
                )
                raise DuplicateDocumentError(original_id=UUID(str(dup[0])))

        # Step 7 — persist bytes to storage.
        document_id = uuid4()
        stored = self.storage.put(
            tenant_id=tenant_id,
            document_id=document_id,
            filename=filename,
            content=content,
            quarantine=quarantined,
        )

        # Step 8 — Document row.
        ingest_state = "quarantined" if quarantined else "received"
        self.session.execute(
            text(
                """
                INSERT INTO document (
                    id, tenant_id, client_id, engagement_id,
                    pbc_request_id, uploaded_by_user_id, filename,
                    content_type, declared_mime, byte_size, sha256,
                    s3_bucket, s3_key, ingest_state, scan_state, scan_engine,
                    scan_finding
                )
                VALUES (
                    :id, :tid, :cid, :eid,
                    :pbc, :uid, :filename,
                    :detected, :declared, :size, :sha,
                    :bucket, :key, :istate, :sstate, :sengine, :sfinding
                )
                """
            ),
            {
                "id": str(document_id),
                "tid": str(tenant_id),
                "cid": str(client_id),
                "eid": str(engagement_id),
                "pbc": str(pbc_request_id) if pbc_request_id else None,
                "uid": str(uploader_user_id),
                "filename": filename,
                "declared": declared_mime,
                "detected": detection.detected_mime,
                "size": size,
                "sha": digest,
                "bucket": stored.bucket,
                "key": stored.object_key,
                "istate": ingest_state,
                "sstate": "infected" if quarantined else "clean",
                "sengine": scan_outcome.engine,
                "sfinding": scan_outcome.finding,
            },
        )

        # Step 9 — audit log.
        emit_audit_event(
            self.session,
            action="document.ingested" if not quarantined else "document.quarantined",
            tenant_id=tenant_id,
            resource_type="document",
            resource_id=document_id,
            actor_user_id=uploader_user_id,
            payload={
                "filename": filename,
                "size_bytes": size,
                "sha256_hex": digest_hex,
                "detected_mime": detection.detected_mime,
                "scan_engine": scan_outcome.engine,
                "scan_finding": scan_outcome.finding,
                "quarantined": quarantined,
                "pbc_request_id": str(pbc_request_id) if pbc_request_id else None,
            },
        )

        return IngestResult(
            document_id=document_id,
            sha256_hex=digest_hex,
            storage_key=f"{stored.bucket}/{stored.object_key}",
            detected_mime=detection.detected_mime,
            size_bytes=size,
            quarantined=quarantined,
            scan_engine=scan_outcome.engine,
            ingest_state=ingest_state,
        )

    # -- helpers --------------------------------------------------------

    def _reject(
        self,
        tenant_id: UUID,
        uploader_user_id: UUID,
        filename: str,
        reason_code: str,
        *,
        extra: dict | None = None,
    ) -> None:
        """Log a rejection without persisting the Document."""
        payload = {
            "filename": filename,
            "reason_code": reason_code,
        }
        if extra:
            payload.update(extra)
        emit_audit_event(
            self.session,
            action="document.rejected",
            tenant_id=tenant_id,
            resource_type="document",
            resource_id=None,
            actor_user_id=uploader_user_id,
            payload=payload,
        )
