"""Ingestion HTTP API — multipart upload + listing + download.

All routes are under ``/ingest`` and require an authenticated session.
The Bearer-token middleware from Task 5 has already pinned
``app.tenant_id`` on the DB session, so these handlers don't pass
tenant IDs manually — they read them from the decoded claims.
"""
from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from accounting_parser.auth.middleware import get_current_claims, get_db_session
from accounting_parser.auth.session import SessionClaims
from accounting_parser.ingestion.service import (
    DuplicateDocumentError,
    IngestionError,
    IngestionService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingestion"])


class DocumentSummary(BaseModel):
    id: UUID
    filename: str
    detected_mime: str
    size_bytes: int
    sha256_hex: str
    ingest_state: str
    scan_state: str
    engagement_id: UUID
    client_id: UUID
    pbc_request_id: UUID | None
    ingested_at: str


class IngestResponse(BaseModel):
    document_id: UUID
    sha256_hex: str
    detected_mime: str
    size_bytes: int
    ingest_state: str
    scan_engine: str
    quarantined: bool


@router.post("/upload", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    claims: Annotated[SessionClaims, Depends(get_current_claims)],
    session: Annotated[Session, Depends(get_db_session)],
    file: UploadFile = File(...),
    firm_id: UUID = Form(...),
    client_id: UUID = Form(...),
    engagement_id: UUID = Form(...),
    pbc_request_id: UUID | None = Form(default=None),
) -> IngestResponse:
    content = await file.read()
    try:
        result = IngestionService(session=session).upload(
            tenant_id=claims.tenant_id,
            firm_id=firm_id,
            client_id=client_id,
            engagement_id=engagement_id,
            uploader_user_id=claims.user_id,
            filename=file.filename or "upload.bin",
            declared_mime=file.content_type or "application/octet-stream",
            content=content,
            pbc_request_id=pbc_request_id,
        )
    except DuplicateDocumentError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "reason_code": e.reason_code,
                "original_document_id": str(e.original_id),
            },
        ) from e
    except IngestionError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={"reason_code": e.reason_code, "message": e.message},
        ) from e

    return IngestResponse(
        document_id=result.document_id,
        sha256_hex=result.sha256_hex,
        detected_mime=result.detected_mime,
        size_bytes=result.size_bytes,
        ingest_state=result.ingest_state,
        scan_engine=result.scan_engine,
        quarantined=result.quarantined,
    )


@router.get("/engagements/{engagement_id}/documents", response_model=list[DocumentSummary])
def list_documents(
    engagement_id: UUID,
    claims: Annotated[SessionClaims, Depends(get_current_claims)],
    session: Annotated[Session, Depends(get_db_session)],
) -> list[DocumentSummary]:
    rows = session.execute(
        text(
            """
            SELECT id, filename, detected_mime, size_bytes, sha256,
                   ingest_state, scan_state, engagement_id, client_id,
                   pbc_request_id, ingested_at
            FROM document
            WHERE engagement_id = :eid
            ORDER BY ingested_at DESC
            """
        ),
        {"eid": str(engagement_id)},
    ).mappings().all()
    return [
        DocumentSummary(
            id=UUID(str(r["id"])),
            filename=r["filename"],
            detected_mime=r["detected_mime"],
            size_bytes=int(r["size_bytes"]),
            sha256_hex=bytes(r["sha256"]).hex(),
            ingest_state=r["ingest_state"],
            scan_state=r["scan_state"],
            engagement_id=UUID(str(r["engagement_id"])),
            client_id=UUID(str(r["client_id"])),
            pbc_request_id=UUID(str(r["pbc_request_id"])) if r["pbc_request_id"] else None,
            ingested_at=r["ingested_at"].isoformat(),
        )
        for r in rows
    ]


@router.get("/documents/{document_id}/content")
def download_document(
    document_id: UUID,
    request: Request,
    claims: Annotated[SessionClaims, Depends(get_current_claims)],
    session: Annotated[Session, Depends(get_db_session)],
) -> Response:
    row = session.execute(
        text(
            """
            SELECT storage_key, filename, detected_mime, ingest_state
            FROM document
            WHERE id = :id
            """
        ),
        {"id": str(document_id)},
    ).mappings().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"reason_code": "document_not_found"},
        )
    if row["ingest_state"] == "quarantined":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"reason_code": "document_quarantined"},
        )
    from accounting_parser.ingestion.storage import get_storage

    storage = get_storage(request.app.state.settings)
    content = storage.get(row["storage_key"])
    return Response(
        content=content,
        media_type=row["detected_mime"],
        headers={"Content-Disposition": f"attachment; filename={row['filename']}"},
    )
