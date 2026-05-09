"""Document ingestion HTTP routes.

- ``POST /engagements/{engagement_id}/documents`` — multipart upload.
- ``GET  /engagements/{engagement_id}/documents`` — list documents.
- ``GET  /documents/{document_id}`` — metadata (not bytes).
- ``GET  /documents/{document_id}/content`` — fetch bytes (P2 adds
  presigned URLs; at P1.2 the route streams directly).

### Error handling

``IngestionError`` subclasses map to specific HTTP status codes:

- ``SizeLimitExceededError``   → 413
- ``InvalidContentTypeError``  → 415
- ``DuplicateDocumentError``   → 409 with ``existing_document_id``
- ``VirusScanError``           → 422 with opaque detail (no
                                 signature leaked to the client)

### Multipart semantics

The route accepts a single ``file`` field. Per request, not per
session — a UI that needs bulk upload sends multiple POSTs. The
service layer is happy with either pattern; simpler to iterate
client-side than to batch server-side at MVP.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from accounting_parser.api.deps import get_current_user, get_db
from accounting_parser.auth.adapter import AuthenticatedUser
from accounting_parser.ingestion.errors import (
    DuplicateDocumentError,
    IngestionError,
    InvalidContentTypeError,
    SizeLimitExceededError,
    VirusScanError,
)
from accounting_parser.ingestion.service import IngestionService
from accounting_parser.storage.adapter import ObjectNotFoundError, ObjectRef

router = APIRouter()


# ---- Response models --------------------------------------------------


class DocumentResponse(BaseModel):
    document_id: str
    filename: str
    content_type: str
    byte_size: int
    sha256_hex: str
    ingest_state: str
    scan_state: str
    uploaded_at: str


class DocumentListResponse(BaseModel):
    engagement_id: str
    documents: list[DocumentResponse]


class UploadResponse(BaseModel):
    document_id: str
    sha256_hex: str
    byte_size: int
    content_type: str


class DuplicateDetail(BaseModel):
    detail: str
    existing_document_id: str


# ---- Handlers ---------------------------------------------------------


@router.post(
    "/engagements/{engagement_id}/documents",
    response_model=UploadResponse,
    status_code=201,
    responses={
        409: {"model": DuplicateDetail},
        413: {"description": "Upload exceeds size limit."},
        415: {"description": "Content type rejected."},
        422: {"description": "Virus scan rejected the upload."},
    },
)
async def upload_document(
    engagement_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> UploadResponse:
    """Ingest a new document for an Engagement."""
    # Resolve the Engagement → Client binding before we touch the
    # stream. A 404 here saves bandwidth for invalid targets.
    row = session.execute(
        text(
            """
            SELECT client_id FROM engagement
            WHERE id = :eid AND tenant_id = :tid
            """
        ),
        {"eid": str(engagement_id), "tid": str(user.tenant_id)},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Engagement not found")
    client_id = UUID(str(row[0]))

    if user.firm_id is None:
        # Signup bug guard: Firm_Administrator users should always
        # have firm_id set. If we see None, refuse rather than
        # write rows with ambiguous ownership.
        raise HTTPException(status_code=403, detail="User has no firm binding")

    settings = request.app.state.settings
    ingestion_service = IngestionService(
        store=request.app.state.document_store,
        scanner=request.app.state.virus_scanner,
        bucket=settings.storage_bucket,
        max_bytes=settings.ingest_max_bytes,
    )

    try:
        result = await ingestion_service.ingest(
            session,
            tenant_id=user.tenant_id,
            firm_id=user.firm_id,
            engagement_id=engagement_id,
            client_id=client_id,
            uploaded_by_user_id=user.user_id,
            filename=file.filename or "untitled",
            declared_content_type=file.content_type or "application/octet-stream",
            stream=file.file,
        )
    except SizeLimitExceededError as e:
        raise HTTPException(status_code=413, detail=str(e)) from e
    except InvalidContentTypeError as e:
        raise HTTPException(status_code=415, detail=str(e)) from e
    except DuplicateDocumentError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "duplicate document",
                "existing_document_id": str(e.existing_document_id),
            },
        ) from e
    except VirusScanError as e:
        # Generic 422 — do NOT include e.signature (prevents a crafted
        # upload from fingerprinting which scanner we run).
        raise HTTPException(status_code=422, detail="upload rejected by security scan") from e
    except IngestionError as e:
        # Catch-all for unknown ingestion errors; surface reason_code
        # so the audit trail and UI can align.
        raise HTTPException(status_code=400, detail=e.reason_code) from e

    return UploadResponse(
        document_id=str(result.document_id),
        sha256_hex=result.sha256_hex,
        byte_size=result.byte_size,
        content_type=result.detected_content_type,
    )


@router.get(
    "/engagements/{engagement_id}/documents",
    response_model=DocumentListResponse,
)
async def list_documents(
    engagement_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> DocumentListResponse:
    """List documents for an Engagement.

    Filters by tenant_id via RLS; the WHERE clause double-scopes for
    defense-in-depth but the RLS policy is the authoritative filter.
    """
    rows = session.execute(
        text(
            """
            SELECT id, filename, content_type, byte_size,
                   encode(sha256, 'hex') AS sha256_hex,
                   ingest_state, scan_state, uploaded_at
            FROM document
            WHERE engagement_id = :eid AND tenant_id = :tid
            ORDER BY uploaded_at DESC
            """
        ),
        {"eid": str(engagement_id), "tid": str(user.tenant_id)},
    ).all()

    documents = [
        DocumentResponse(
            document_id=str(r[0]),
            filename=r[1],
            content_type=r[2],
            byte_size=int(r[3]),
            sha256_hex=r[4],
            ingest_state=r[5],
            scan_state=r[6],
            uploaded_at=r[7].isoformat(),
        )
        for r in rows
    ]
    return DocumentListResponse(
        engagement_id=str(engagement_id),
        documents=documents,
    )


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> DocumentResponse:
    """Fetch document metadata. Bytes live at ``/documents/{id}/content``."""
    row = session.execute(
        text(
            """
            SELECT id, filename, content_type, byte_size,
                   encode(sha256, 'hex') AS sha256_hex,
                   ingest_state, scan_state, uploaded_at
            FROM document
            WHERE id = :id AND tenant_id = :tid
            """
        ),
        {"id": str(document_id), "tid": str(user.tenant_id)},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentResponse(
        document_id=str(row[0]),
        filename=row[1],
        content_type=row[2],
        byte_size=int(row[3]),
        sha256_hex=row[4],
        ingest_state=row[5],
        scan_state=row[6],
        uploaded_at=row[7].isoformat(),
    )


@router.get("/documents/{document_id}/content")
async def get_document_content(
    document_id: UUID,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db),
):
    """Stream document bytes.

    P2 will replace this with presigned S3 URL redirects so the API
    server doesn't stream bytes itself. At P1.2 it's a straight
    pass-through, which keeps the route simple and mandates no new
    caching infrastructure.
    """
    from fastapi.responses import StreamingResponse

    row = session.execute(
        text(
            """
            SELECT s3_bucket, s3_key, content_type, filename
            FROM document
            WHERE id = :id AND tenant_id = :tid
            """
        ),
        {"id": str(document_id), "tid": str(user.tenant_id)},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")

    store = request.app.state.document_store
    ref = ObjectRef(bucket=str(row[0]), key=str(row[1]))
    try:
        stream = store.retrieve(ref)
    except ObjectNotFoundError as e:
        # Row exists but object doesn't: storage drift (backup
        # restore gone wrong, manual MinIO tampering). 404 the
        # route so the client sees a consistent "not found" shape.
        raise HTTPException(status_code=404, detail="Object not found") from e

    def _iter():
        try:
            while chunk := stream.read(65536):
                yield chunk
        finally:
            if hasattr(stream, "close"):
                stream.close()

    return StreamingResponse(
        _iter(),
        media_type=str(row[2]),
        headers={"Content-Disposition": f'attachment; filename="{row[3]}"'},
    )
