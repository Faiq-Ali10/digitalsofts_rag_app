"""FastAPI application factory.

Creates the main application with all middleware, routers, and lifecycle hooks.
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.auth import router as auth_router
from app.api.v1.chat import router as chat_router
from app.api.v1.documents import router as documents_router
from app.api.v1.health import router as health_router
from app.api.v1.health import REQUEST_COUNT, REQUEST_LATENCY
from app.config import get_settings
from app.observability.logging import setup_logging

settings = get_settings()
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle — startup and shutdown hooks."""
    # Startup
    setup_logging(
        log_level=settings.log_level,
        json_format=settings.is_production,
    )

    # Register agent tools
    from app.tools.registry import register_all_tools
    register_all_tools()

    logger.info(
        "application_starting",
        app_name=settings.app_name,
        env=settings.app_env,
    )
    yield
    # Shutdown
    logger.info("application_shutting_down")


app = FastAPI(
    title="Digitalsofts AI Assistant",
    description="Enterprise AI Knowledge & Action Assistant API",
    version="0.1.0",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    lifespan=lifespan,
)

# ── Middleware ───────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_middleware(request: Request, call_next) -> Response:
    """Add request ID, structured logging context, and latency tracking."""
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    # Bind request context for all logs within this request
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
    )

    start_time = time.monotonic()

    try:
        response = await call_next(request)
    except Exception as exc:
        logger.error("unhandled_exception", error=str(exc), exc_info=True)
        response = JSONResponse(
            status_code=500,
            content={
                "data": None,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An internal error occurred",
                },
            },
        )

    latency = time.monotonic() - start_time

    # Add headers
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time"] = f"{latency:.3f}s"

    # Record metrics
    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code,
    ).inc()
    REQUEST_LATENCY.labels(
        method=request.method,
        endpoint=request.url.path,
    ).observe(latency)

    # Log request completion
    logger.info(
        "request_completed",
        status_code=response.status_code,
        latency_ms=round(latency * 1000),
    )

    return response


# ── Global Exception Handlers ────────────────────────────────────────────────


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content={
            "data": None,
            "error": {"code": "NOT_FOUND", "message": "Resource not found"},
        },
    )


@app.exception_handler(422)
async def validation_error_handler(request: Request, exc):
    return JSONResponse(
        status_code=422,
        content={
            "data": None,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "details": getattr(exc, "detail", str(exc)),
            },
        },
    )


# ── Routers ──────────────────────────────────────────────────────────────────

app.include_router(health_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")


@app.get("/", include_in_schema=False)
async def root():
    return {
        "name": settings.app_name,
        "version": "0.1.0",
        "docs": "/docs",
    }
