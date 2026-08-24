"""Document ingestion pipeline orchestrator.

Coordinates parsing, chunking, embedding, and indexing into a single
pipeline. Called by the Arq worker for async processing.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Document, DocumentChunk, DocumentStatus, DocumentType
from app.ingestion.chunking import chunk_document
from app.ingestion.parsers.base import DocumentParser
from app.ingestion.parsers.html_parser import HTMLParser
from app.ingestion.parsers.markdown_parser import MarkdownParser
from app.ingestion.parsers.pdf_parser import PDFParser
from app.ingestion.parsers.text_parser import TextParser
from app.llm.embeddings import get_embedding_provider

settings = get_settings()
logger = structlog.get_logger(__name__)

# Parser registry
PARSERS: dict[DocumentType, DocumentParser] = {
    DocumentType.PDF: PDFParser(),
    DocumentType.MARKDOWN: MarkdownParser(),
    DocumentType.HTML: HTMLParser(),
    DocumentType.TEXT: TextParser(),
}


async def ingest_document(
    document_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    """Run the full ingestion pipeline for a document.

    Pipeline stages:
    1. Load document record from DB
    2. Parse file content
    3. Check for duplicates (content hash)
    4. Chunk text
    5. Generate embeddings
    6. Store chunks + vectors in DB
    7. Update document status

    Args:
        document_id: UUID of the document to ingest.
        db: Async database session.
    """
    logger.info("ingestion_started", document_id=str(document_id))

    # 1. Load document
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()

    if doc is None:
        logger.error("document_not_found", document_id=str(document_id))
        return

    # Update status to processing
    doc.status = DocumentStatus.PROCESSING
    await db.commit()

    try:
        # 2. Parse file
        parser = PARSERS.get(doc.document_type)
        if parser is None:
            raise ValueError(f"No parser for document type: {doc.document_type}")

        if doc.file_path:
            parsed = parser.parse(doc.file_path)
        else:
            logger.error("no_file_path", document_id=str(document_id))
            raise ValueError("Document has no file path")

        if parsed.is_empty:
            raise ValueError("Document content is empty after parsing")

        # 3. Check duplicate
        content_hash = parsed.content_hash
        existing = await db.execute(
            select(Document).where(
                Document.content_hash == content_hash,
                Document.id != document_id,
            )
        )
        if existing.scalar_one_or_none():
            logger.warning(
                "duplicate_document",
                document_id=str(document_id),
                hash=content_hash,
            )
            doc.status = DocumentStatus.FAILED
            doc.error_message = "Duplicate document content detected"
            doc.content_hash = content_hash
            await db.commit()
            return

        doc.content_hash = content_hash

        # 4. Chunk
        base_metadata = {
            "document_id": str(document_id),
            "title": doc.title,
            "source": doc.source,
            "document_type": doc.document_type.value,
        }
        if doc.product:
            base_metadata["product"] = doc.product
        if doc.version:
            base_metadata["version"] = doc.version

        # Merge parser-extracted metadata
        base_metadata.update(parsed.metadata)

        chunks = chunk_document(
            content=parsed.content,
            base_metadata=base_metadata,
            sections=parsed.sections if parsed.sections else None,
        )

        if not chunks:
            raise ValueError("No chunks produced from document")

        logger.info(
            "chunks_created",
            document_id=str(document_id),
            chunk_count=len(chunks),
        )

        # 5. Generate embeddings
        embedder = get_embedding_provider()
        chunk_texts = [c.content for c in chunks]

        # Batch embeddings (process in groups of 64 to avoid memory issues)
        all_embeddings: list[list[float]] = []
        batch_size = 64
        for i in range(0, len(chunk_texts), batch_size):
            batch = chunk_texts[i : i + batch_size]
            response = await embedder.embed(batch)
            all_embeddings.extend(response.embeddings)

        # 6. Delete old chunks (for re-ingestion)
        await db.execute(
            DocumentChunk.__table__.delete().where(DocumentChunk.document_id == document_id)
        )

        # 7. Store new chunks
        for chunk, embedding in zip(chunks, all_embeddings):
            db_chunk = DocumentChunk(
                document_id=document_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                embedding=embedding,
                metadata_=chunk.metadata,
                token_count=chunk.token_count_estimate,
            )
            db.add(db_chunk)

        # 8. Update document status
        doc.status = DocumentStatus.COMPLETED
        doc.chunk_count = len(chunks)
        doc.error_message = None

        await db.commit()

        logger.info(
            "ingestion_completed",
            document_id=str(document_id),
            chunks=len(chunks),
        )

    except Exception as e:
        logger.error(
            "ingestion_failed",
            document_id=str(document_id),
            error=str(e),
            exc_info=True,
        )
        await db.rollback()

        # Update status to failed
        await db.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(
                status=DocumentStatus.FAILED,
                error_message=str(e)[:1000],
            )
        )
        await db.commit()
