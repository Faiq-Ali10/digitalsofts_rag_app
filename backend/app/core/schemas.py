"""Shared Pydantic models for standardized API responses and errors."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    """Structured error information."""

    code: str
    message: str
    details: dict[str, Any] | None = None


class APIResponse(BaseModel, Generic[T]):
    """Standardized API response wrapper.

    All API endpoints return responses in this format for consistency.
    """

    data: T | None = None
    error: ErrorDetail | None = None
    metadata: dict[str, Any] | None = None


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated list response."""

    items: list[T]
    total: int
    page: int = 1
    page_size: int = 20
    has_more: bool = False


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str = "0.1.0"
    checks: dict[str, str] = Field(default_factory=dict)
