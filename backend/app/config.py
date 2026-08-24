"""Digitalsofts AI Assistant — Application Configuration.

Centralized configuration using pydantic-settings.
All settings are loaded from environment variables with sensible defaults.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────
    app_name: str = "digitalsofts-ai-assistant"
    app_env: Literal["development", "staging", "production"] = "development"
    debug: bool = True
    log_level: str = "INFO"
    secret_key: str = "change-me-to-a-random-secret-key-min-32-chars"

    # ── Database ─────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/digitalsofts"
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # ── Redis ────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── Auth / JWT ───────────────────────────────────────────────────────
    jwt_secret_key: str = "change-me-to-a-different-random-secret"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # ── LLM Providers ───────────────────────────────────────────────────
    gemini_api_key: str = ""
    groq_api_key: str = ""
    llm_primary_model: str = "gemini/gemini-3.6-flash"
    llm_fallback_model: str = "groq/llama-3.1-70b-versatile"
    llm_eval_model: str = "gemini/gemini-3.6-flash"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 2048
    llm_timeout_seconds: int = 30
    llm_max_retries: int = 3

    # ── Embeddings ───────────────────────────────────────────────────────
    embedding_model_name: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384

    # ── RAG Settings ─────────────────────────────────────────────────────
    rag_chunk_size: int = 1000
    rag_chunk_overlap: int = 200
    rag_top_k: int = 20
    rag_rerank_top_k: int = 5
    rag_similarity_threshold: float = 0.3

    # ── Langfuse ─────────────────────────────────────────────────────────
    langfuse_enabled: bool = False
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3000"

    # ── CORS ─────────────────────────────────────────────────────────────
    cors_origins: list[str] = Field(default=["http://localhost:3000", "http://localhost:8000"])

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return json.loads(v)
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def database_url_sync(self) -> str:
        """Synchronous database URL for Alembic migrations."""
        return self.database_url.replace("+asyncpg", "+psycopg2")


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
