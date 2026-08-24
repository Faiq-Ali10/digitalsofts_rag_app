"""Document management API endpoints.

POST   /api/v1/documents              — Upload a document for ingestion
POST   /api/v1/documents/{id}/ingest  — Re-trigger ingestion
GET    /api/v1/documents              — List all documents
GET    /api/v1/documents/{id}         — Get document details
DELETE /api/v1/documents/{id}         — Delete a document
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import structlog
from arq.connections import create_pool
from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.config import get_settings
from app.core.schemas import APIResponse, PaginatedResponse
from app.db.models import Document, DocumentStatus, DocumentType, User, UserRole
from app.db.session import get_db
from app.ingestion.worker import _parse_redis_url

settings = get_settings()
router = APIRouter(prefix="/documents", tags=["Documents"])
logger = structlog.get_logger(__name__)

# File upload directory
UPLOAD_DIR = Path("/data/raw/uploads")


# ── Schemas ──────────────────────────────────────────────────────────────────


class DocumentCreate(BaseModel):
    title: str = Field(max_length=500)
    product: str | None = Field(default=None, max_length=255)
    version: str | None = Field(default=None, max_length=50)


class DocumentResponse(BaseModel):
    id: uuid.UUID
    title: str
    source: str
    document_type: str
    product: str | None
    version: str | None
    status: str
    chunk_count: int
    error_message: str | None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


# ── File Type Detection ──────────────────────────────────────────────────────

EXTENSION_MAP: dict[str, DocumentType] = {
    ".pdf": DocumentType.PDF,
    ".md": DocumentType.MARKDOWN,
    ".markdown": DocumentType.MARKDOWN,
    ".html": DocumentType.HTML,
    ".htm": DocumentType.HTML,
    ".txt": DocumentType.TEXT,
    ".text": DocumentType.TEXT,
}


def detect_document_type(filename: str) -> DocumentType:
    """Detect document type from file extension."""
    ext = Path(filename).suffix.lower()
    doc_type = EXTENSION_MAP.get(ext)
    if doc_type is None:
        raise ValueError(f"Unsupported file type: {ext}")
    return doc_type


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=APIResponse[DocumentResponse],
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def upload_document(
    file: UploadFile,
    title: str = "",
    product: str | None = None,
    version: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse:
    """Upload a document and queue it for asynchronous ingestion.

    Only ADMIN users can upload documents.
    Returns 202 Accepted with the document record (status=pending).
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    # Detect type
    try:
        doc_type = detect_document_type(file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Read file content
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="File is empty")

    # Generate content hash for dedup
    content_hash = hashlib.sha256(content).hexdigest()

    # Check for existing document with same hash
    existing = await db.execute(
        select(Document).where(Document.content_hash == content_hash)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A document with identical content already exists",
        )

    # Save file to disk
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4()
    file_path = UPLOAD_DIR / f"{file_id}_{file.filename}"
    file_path.write_bytes(content)

    # Create document record
    doc_title = title or Path(file.filename).stem.replace("-", " ").replace("_", " ").title()

    doc = Document(
        title=doc_title,
        source=file.filename,
        document_type=doc_type,
        product=product,
        version=version,
        content_hash=content_hash,
        file_path=str(file_path),
        file_size_bytes=len(content),
        status=DocumentStatus.PENDING,
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)

    # Queue ingestion job
    try:
        redis = await create_pool(_parse_redis_url(settings.redis_url))
        await redis.enqueue_job("ingest_document_task", str(doc.id))
        await redis.close()
        logger.info("ingestion_queued", document_id=str(doc.id))
    except Exception as e:
        logger.error("queue_failed", error=str(e))
        # Don't fail the upload — document is saved, can be re-triggered

    return APIResponse(
        data=DocumentResponse(
            id=doc.id,
            title=doc.title,
            source=doc.source,
            document_type=doc.document_type.value,
            product=doc.product,
            version=doc.version,
            status=doc.status.value,
            chunk_count=doc.chunk_count,
            error_message=doc.error_message,
            created_at=doc.created_at.isoformat(),
            updated_at=doc.updated_at.isoformat(),
        ),
        metadata={"message": "Document uploaded and queued for ingestion"},
    )


@router.post(
    "/{document_id}/ingest",
    response_model=APIResponse[DocumentResponse],
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def reingest_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """Re-trigger ingestion for an existing document."""
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()

    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    doc.status = DocumentStatus.PENDING
    doc.error_message = None
    await db.flush()

    # Queue job
    try:
        redis = await create_pool(_parse_redis_url(settings.redis_url))
        await redis.enqueue_job("ingest_document_task", str(doc.id))
        await redis.close()
    except Exception as e:
        logger.error("requeue_failed", error=str(e))

    return APIResponse(
        data=DocumentResponse(
            id=doc.id,
            title=doc.title,
            source=doc.source,
            document_type=doc.document_type.value,
            product=doc.product,
            version=doc.version,
            status=doc.status.value,
            chunk_count=doc.chunk_count,
            error_message=doc.error_message,
            created_at=doc.created_at.isoformat(),
            updated_at=doc.updated_at.isoformat(),
        ),
        metadata={"message": "Document re-queued for ingestion"},
    )


@router.get("", response_model=APIResponse[PaginatedResponse[DocumentResponse]])
async def list_documents(
    page: int = 1,
    page_size: int = 20,
    status_filter: str | None = None,
    product: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse:
    """List all documents with optional filtering."""
    query = select(Document)

    if status_filter:
        query = query.where(Document.status == status_filter)
    if product:
        query = query.where(Document.product == product)

    # Count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Paginate
    query = query.order_by(Document.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    docs = result.scalars().all()

    items = [
        DocumentResponse(
            id=d.id,
            title=d.title,
            source=d.source,
            document_type=d.document_type.value,
            product=d.product,
            version=d.version,
            status=d.status.value,
            chunk_count=d.chunk_count,
            error_message=d.error_message,
            created_at=d.created_at.isoformat(),
            updated_at=d.updated_at.isoformat(),
        )
        for d in docs
    ]

    return APIResponse(
        data=PaginatedResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            has_more=(page * page_size) < total,
        )
    )


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def delete_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a document and all its chunks (cascade)."""
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()

    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    # Delete file from disk
    if doc.file_path:
        file_path = Path(doc.file_path)
        if file_path.exists():
            file_path.unlink()

    await db.delete(doc)
    logger.info("document_deleted", document_id=str(document_id))
