"""Arq background worker for asynchronous document ingestion.

Documents are queued for processing via Redis. The worker picks up
jobs and runs the ingestion pipeline without blocking API requests.
"""

from __future__ import annotations

import uuid

import structlog
from arq.connections import RedisSettings

from app.config import get_settings

settings = get_settings()
logger = structlog.get_logger(__name__)


async def ingest_document_task(ctx: dict, document_id: str) -> dict:
    """Arq task: Run the ingestion pipeline for a document.

    Args:
        ctx: Arq context (contains redis connection).
        document_id: UUID string of the document to process.

    Returns:
        Dict with status and details.
    """
    from app.db.session import async_session_factory
    from app.ingestion.pipeline import ingest_document

    logger.info("worker_task_started", document_id=document_id)

    try:
        async with async_session_factory() as session:
            await ingest_document(uuid.UUID(document_id), session)

        return {"status": "completed", "document_id": document_id}

    except Exception as e:
        logger.error(
            "worker_task_failed",
            document_id=document_id,
            error=str(e),
            exc_info=True,
        )
        return {"status": "failed", "document_id": document_id, "error": str(e)}


async def startup(ctx: dict) -> None:
    """Worker startup hook — initialize resources."""
    logger.info("arq_worker_starting")

    # Pre-load embedding model to avoid first-request latency
    from app.llm.embeddings import get_embedding_provider
    get_embedding_provider()

    logger.info("arq_worker_ready")


async def shutdown(ctx: dict) -> None:
    """Worker shutdown hook — clean up resources."""
    logger.info("arq_worker_shutting_down")


def _parse_redis_url(url: str) -> RedisSettings:
    """Parse redis:// URL into RedisSettings."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or "0"),
        password=parsed.password,
    )


class WorkerSettings:
    """Arq worker configuration."""

    functions = [ingest_document_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _parse_redis_url(settings.redis_url)

    # Worker behavior
    max_jobs = 5  # Max concurrent jobs
    job_timeout = 600  # 10 minute timeout per job
    max_tries = 3  # Retry failed jobs up to 3 times
    retry_delay = 30  # Wait 30 seconds before retry
    health_check_interval = 30
