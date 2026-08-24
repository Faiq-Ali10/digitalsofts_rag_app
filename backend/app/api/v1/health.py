"""Health, readiness, and metrics endpoints.

GET /api/v1/health  — Liveness probe (always 200 if app is running)
GET /api/v1/ready   — Readiness probe (checks DB + Redis connectivity)
GET /api/v1/metrics — Prometheus-format application metrics
"""

from __future__ import annotations

import time

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from prometheus_client import (
    Counter,
    Histogram,
    generate_latest,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.schemas import HealthResponse
from app.db.session import get_db

router = APIRouter(tags=["Health"])
logger = structlog.get_logger(__name__)

# ── Prometheus Metrics ───────────────────────────────────────────────────────

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
)

LLM_TOKENS = Counter(
    "llm_tokens_total",
    "Total LLM tokens consumed",
    ["model", "type"],
)

LLM_LATENCY = Histogram(
    "llm_request_duration_seconds",
    "LLM request latency in seconds",
    ["model"],
)

RETRIEVAL_LATENCY = Histogram(
    "retrieval_duration_seconds",
    "Retrieval latency in seconds",
)

TOOL_CALLS = Counter(
    "tool_calls_total",
    "Total tool calls",
    ["tool_name", "status"],
)

INGESTION_JOBS = Counter(
    "ingestion_jobs_total",
    "Total document ingestion jobs",
    ["status"],
)


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Liveness probe — returns 200 if the application is running."""
    return HealthResponse(status="healthy")


@router.get("/ready", response_model=HealthResponse)
async def readiness_check(
    db: AsyncSession = Depends(get_db),
) -> HealthResponse:
    """Readiness probe — checks database and Redis connectivity."""
    checks: dict[str, str] = {}

    # Check PostgreSQL
    try:
        start = time.monotonic()
        await db.execute(text("SELECT 1"))
        latency = (time.monotonic() - start) * 1000
        checks["postgres"] = f"ok ({latency:.0f}ms)"
    except Exception as e:
        logger.error("readiness_check_failed", component="postgres", error=str(e))
        checks["postgres"] = f"error: {e}"

    # Check Redis
    try:
        import redis.asyncio as aioredis

        from app.config import get_settings

        settings = get_settings()
        r = aioredis.from_url(settings.redis_url)
        start = time.monotonic()
        await r.ping()
        latency = (time.monotonic() - start) * 1000
        checks["redis"] = f"ok ({latency:.0f}ms)"
        await r.close()
    except Exception as e:
        logger.error("readiness_check_failed", component="redis", error=str(e))
        checks["redis"] = f"error: {e}"

    all_ok = all(v.startswith("ok") for v in checks.values())

    return HealthResponse(
        status="ready" if all_ok else "degraded",
        checks=checks,
    )


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> PlainTextResponse:
    """Prometheus-format metrics endpoint."""
    return PlainTextResponse(
        content=generate_latest().decode("utf-8"),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
