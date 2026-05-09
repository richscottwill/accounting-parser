"""IngestionService — end-to-end upload orchestration.

Called by the documents upload route. Never called directly from
workers or scripts — the service assumes it has a live SQLAlchemy
session with the tenant context pinned.

### Flow

```
    receive stream + metadata
        │
        ▼
    enforce byte-size limit       (SizeLimitExceededError → 413)
        │
        ▼
    detect content-type via magic bytes
    compare to declared            (InvalidContentTypeError → 415)
        │
        ▼
    compute sha256 (single pass)
        │
        ▼
    check ``document`` for dup     (DuplicateDocumentError → 409)
        │
        ▼
    virus scan                     (VirusScanError → 422 + quarantine)
        │
        ▼
    store bytes in MinIO under firm/client/sha256/ prefix
        │
        ▼
    insert document row (dedup constraint as backstop)
        │
        ▼
    audit event ``document.ingested``
        │
        ▼
    return IngestionResult with document_id
```

### Error-path audit discipline

Every rejection path produces an ``auth`` / ``document`` audit event
inside a nested savepoint so the outer rollback on ``raise`` doesn't
discard the audit row. Same pattern as ``AuthService.consume_magic_link``
from P1.1 — hardened into a helper so future ingest errors use it
uniformly. Commits the rejection audit only, then raises; the caller
sees a clean failure with a record of the rejection in the audit log.
"""

from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass
from typing import Any, BinaryIO
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from accounting_parser.auth.audit import append_auth_event
from accounting_parser.ingestion.errors import (
    DuplicateDocumentError,
    InvalidContentTypeError,
    SizeLimitExceededError,
    VirusScanError,
)
from accounting_parser.ingestion.magic_bytes import detect_content_type, is_accepted
from accounting_parser.ingestion.virus_scan import VirusScanner
from accounting_parser.storage.adapter import DocumentStoreAdapter, ObjectRef, build_key

logger = logging.getLogger(__name__)


DEFAULT_MAX_BYTES = 100 * 1024 * 1024  # 100 MB per parent R22.1
_HEAD_SAMPLE_BYTES = 4096  # big enough for magic-byte + xlsx probe


@dataclass(frozen=True)
class IngestionResult:
    """What the service returns on a successful ingest.

    ``sha256_hex`` is returned so the route can echo it to the client
    for end-to-end integrity verification. ``object_key`` lets the
    client address the object through an authenticated presigned-URL
    flow later (P2 work); at P1.2 the route doesn't expose this.
    """

    document_id: UUID
    sha256_hex: str
    byte_size: int
    detected_content_type: str
    object_key: str
    bucket: str


class IngestionService:
    """Stateless. Holds references to its adapters; methods take the
    session + request payload as arguments.

    Thread-safe: the adapters are thread-safe (boto3 is; the virus
    scanner may create per-call clients or hold a pool).
    """

    def __init__(
        self,
        *,
        store: DocumentStoreAdapter,
        scanner: VirusScanner,
        bucket: str,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> None:
        self.store = store
        self.scanner = scanner
        self.bucket = bucket
        self.max_bytes = max_bytes

    async def ingest(
        self,
        session: Session,
        *,
        tenant_id: UUID,
        firm_id: UUID,
        engagement_id: UUID,
        client_id: UUID,
        uploaded_by_user_id: UUID,
        filename: str,
        declared_content_type: str,
        stream: BinaryIO,
    ) -> IngestionResult:
        """Run the full ingestion pipeline, returning on success.

        Raises ``IngestionError`` subclasses on any validation failure;
        each raise is accompanied by a committed audit event.
        """
        # ---- Step 1: buffer + size limit -----------------------
        # We fully buffer in memory for files up to max_bytes. This
        # bounds RAM at ~max_bytes per concurrent request (100 MB
        # cap means 10 concurrent uploads = 1 GB worst case). For a
        # single-CPA deployment this is well within budget; a real
        # multi-tenant deployment would stream to temp files. The
        # adapter interface supports either — simpler first.
        buffered = io.BytesIO()
        read = 0
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            read += len(chunk)
            if read > self.max_bytes:
                self._audit_rejection(
                    session,
                    tenant_id=tenant_id,
                    uploaded_by_user_id=uploaded_by_user_id,
                    filename=filename,
                    reason_code="size_limit_exceeded",
                    detail={"byte_size": read, "limit": self.max_bytes},
                )
                raise SizeLimitExceededError(byte_size=read, limit=self.max_bytes)
            buffered.write(chunk)
        buffered.seek(0)

        if read == 0:
            self._audit_rejection(
                session,
                tenant_id=tenant_id,
                uploaded_by_user_id=uploaded_by_user_id,
                filename=filename,
                reason_code="empty_upload",
                detail={},
            )
            raise InvalidContentTypeError(declared=declared_content_type, detected="empty")

        # ---- Step 2: content-type detection ---------------------
        head_sample = buffered.read(_HEAD_SAMPLE_BYTES)
        buffered.seek(0)
        detected = detect_content_type(head_sample)

        if not is_accepted(detected):
            self._audit_rejection(
                session,
                tenant_id=tenant_id,
                uploaded_by_user_id=uploaded_by_user_id,
                filename=filename,
                reason_code="invalid_content_type",
                detail={"declared": declared_content_type, "detected": detected},
            )
            raise InvalidContentTypeError(declared=declared_content_type, detected=detected)

        # Declared-vs-detected cross-check. We don't require exact
        # match (a client can upload 'application/octet-stream' for
        # unknown types), but a lying declaration ("PDF" for an xlsx)
        # is a bad signal worth auditing.
        if (
            declared_content_type
            and declared_content_type != "application/octet-stream"
            and declared_content_type != detected
        ):
            # Not fatal — some MIME variants are acceptable (e.g.,
            # "application/x-pdf" vs "application/pdf"). Log and move
            # on; the detected type is authoritative for persistence.
            logger.info(
                "content_type_declared_vs_detected_mismatch",
                extra={"declared": declared_content_type, "detected": detected},
            )

        # ---- Step 3: sha256 + virus scan ------------------------
        buffered.seek(0)
        digest = hashlib.sha256()
        while chunk := buffered.read(65536):
            digest.update(chunk)
        sha256_hex = digest.hexdigest()
        sha256_bytes = bytes.fromhex(sha256_hex)

        buffered.seek(0)
        try:
            scan_result = self.scanner.scan(buffered)
        except Exception as e:  # noqa: BLE001
            # Scanner unavailable: fail closed, audit, raise.
            self._audit_rejection(
                session,
                tenant_id=tenant_id,
                uploaded_by_user_id=uploaded_by_user_id,
                filename=filename,
                reason_code="scanner_unavailable",
                detail={"error": type(e).__name__},
            )
            raise VirusScanError(signature="scanner_unavailable") from e

        if not scan_result.is_clean:
            self._audit_rejection(
                session,
                tenant_id=tenant_id,
                uploaded_by_user_id=uploaded_by_user_id,
                filename=filename,
                reason_code="virus_detected",
                detail={
                    # Named scan_signature (not 'signature') to avoid
                    # the audit scrubber treating it like a crypto
                    # signature. scan_signature is the clamd virus-
                    # name tag (e.g., "Win.Test.EICAR_HDB-1") — safe
                    # to retain in the audit log.
                    "scan_signature": scan_result.signature,
                    "scanner_version": scan_result.scanner_version,
                },
            )
            # Stash the quarantined bytes under a separate prefix so
            # incident response can retrieve them without touching the
            # normal document path. We do NOT insert a document row —
            # the quarantined upload is not a document.
            buffered.seek(0)
            quarantine_key = f"firms/{firm_id}/quarantine/{sha256_hex}/{filename}"
            try:
                self.store.store(
                    ObjectRef(bucket=self.bucket, key=quarantine_key),
                    buffered,
                    content_type=detected,
                    content_length=read,
                )
            except Exception as e:  # noqa: BLE001
                # Quarantine write failure is non-fatal to the
                # rejection — we still reject; log for ops.
                logger.error(
                    "quarantine_write_failed", extra={"key": quarantine_key, "error": str(e)}
                )
            raise VirusScanError(signature=scan_result.signature or "unknown")

        # ---- Step 4: dedup pre-check ---------------------------
        # Constraint is the authoritative check; we pre-query for a
        # friendly error message with the existing document id.
        existing = session.execute(
            text(
                """
                SELECT id FROM document
                WHERE tenant_id = :tid AND client_id = :cid AND sha256 = :sh
                """
            ),
            {"tid": str(tenant_id), "cid": str(client_id), "sh": sha256_bytes},
        ).scalar_one_or_none()

        if existing is not None:
            self._audit_rejection(
                session,
                tenant_id=tenant_id,
                uploaded_by_user_id=uploaded_by_user_id,
                filename=filename,
                reason_code="duplicate_document",
                detail={"existing_document_id": str(existing), "sha256": sha256_hex},
                resource_id=UUID(str(existing)),
            )
            raise DuplicateDocumentError(existing_document_id=UUID(str(existing)))

        # ---- Step 5: store bytes ------------------------------
        object_key = build_key(
            firm_id=firm_id,
            client_id=client_id,
            sha256_hex=sha256_hex,
            filename=filename,
        )
        ref = ObjectRef(bucket=self.bucket, key=object_key)
        buffered.seek(0)
        self.store.store(ref, buffered, content_type=detected, content_length=read)

        # ---- Step 6: insert document row ----------------------
        document_id = uuid4()
        try:
            session.execute(
                text(
                    """
                    INSERT INTO document (
                        id, tenant_id, engagement_id, client_id,
                        filename, content_type, byte_size, sha256,
                        s3_bucket, s3_key, ingest_state, uploaded_by_user_id
                    ) VALUES (
                        :id, :tid, :eid, :cid,
                        :fn, :ct, :bs, :sh,
                        :bk, :ky, 'uploaded', :uid
                    )
                    """
                ),
                {
                    "id": str(document_id),
                    "tid": str(tenant_id),
                    "eid": str(engagement_id),
                    "cid": str(client_id),
                    "fn": filename,
                    "ct": detected,
                    "bs": read,
                    "sh": sha256_bytes,
                    "bk": self.bucket,
                    "ky": object_key,
                    "uid": str(uploaded_by_user_id),
                },
            )
        except IntegrityError as e:
            # A concurrent upload beat us to the dedup constraint.
            # Roll back our object upload (if the row conflicts,
            # the pre-check missed a race) and re-raise as a
            # DuplicateDocumentError with the now-existing id.
            self.store.delete(ref)
            existing_id = session.execute(
                text(
                    """
                    SELECT id FROM document
                    WHERE tenant_id = :tid AND client_id = :cid AND sha256 = :sh
                    """
                ),
                {"tid": str(tenant_id), "cid": str(client_id), "sh": sha256_bytes},
            ).scalar_one_or_none()
            if existing_id is None:
                # Constraint violated but row not found — unexpected.
                # Re-raise the original exception so the route returns
                # 500; operators inspect the audit log + DB state.
                raise
            self._audit_rejection(
                session,
                tenant_id=tenant_id,
                uploaded_by_user_id=uploaded_by_user_id,
                filename=filename,
                reason_code="duplicate_document",
                detail={
                    "existing_document_id": str(existing_id),
                    "sha256": sha256_hex,
                    "race": True,
                },
                resource_id=UUID(str(existing_id)),
            )
            raise DuplicateDocumentError(existing_document_id=UUID(str(existing_id))) from e

        # ---- Step 7: audit success ----------------------------
        append_auth_event(
            session,
            tenant_id=tenant_id,
            actor_user_id=uploaded_by_user_id,
            action="document.ingested",
            resource_id=document_id,
            payload={
                "filename": filename,
                "content_type": detected,
                "byte_size": read,
                "sha256": sha256_hex,
                "bucket": self.bucket,
                "object_key": object_key,
            },
        )

        return IngestionResult(
            document_id=document_id,
            sha256_hex=sha256_hex,
            byte_size=read,
            detected_content_type=detected,
            object_key=object_key,
            bucket=self.bucket,
        )

    # ---- Internal helpers ----------------------------------------

    def _audit_rejection(
        self,
        session: Session,
        *,
        tenant_id: UUID,
        uploaded_by_user_id: UUID,
        filename: str,
        reason_code: str,
        detail: dict[str, Any],
        resource_id: UUID | None = None,
    ) -> None:
        """Commit a ``document.rejected`` audit event inside a savepoint.

        Same pattern as ``AuthService.consume_magic_link`` — the outer
        transaction is about to roll back via ``raise``, but the
        rejection audit must persist. Nested savepoint + explicit
        commit accomplishes that cleanly.
        """
        with session.begin_nested():
            append_auth_event(
                session,
                tenant_id=tenant_id,
                actor_user_id=uploaded_by_user_id,
                action="document.rejected",
                resource_id=resource_id,
                payload={
                    "filename": filename,
                    "reason_code": reason_code,
                    **detail,
                },
            )
        session.commit()
