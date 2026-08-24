"""Test configuration and shared fixtures."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import Settings
from app.db.models import User, UserRole
from app.llm.provider import EmbeddingResponse, LLMResponse


@pytest.fixture(scope="session")
def event_loop():
    """Create a shared event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def test_settings():
    """Override settings for testing."""
    return Settings(
        app_env="development",
        debug=True,
        database_url="sqlite+aiosqlite:///test.db",
        jwt_secret_key="test-secret-key-for-testing-only",  # noqa: S106
        gemini_api_key="test-key",
        llm_primary_model="gemini/gemini-3.6-flash",
    )


@pytest.fixture
def mock_user():
    """Create a mock user for testing."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "test@example.com"
    user.full_name = "Test User"
    user.role = UserRole.USER
    user.is_active = True
    return user


@pytest.fixture
def mock_admin_user():
    """Create a mock admin user for testing."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "admin@example.com"
    user.full_name = "Admin User"
    user.role = UserRole.ADMIN
    user.is_active = True
    return user


@pytest.fixture
def mock_llm_provider():
    """Mock LLM provider that returns controlled responses."""
    provider = AsyncMock()
    provider.complete = AsyncMock(
        return_value=LLMResponse(
            content='{"intent": "knowledge", "confidence": 0.9, "reasoning": "test"}',
            model="test-model",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            latency_ms=500,
        )
    )
    return provider


@pytest.fixture
def mock_embedding_provider():
    """Mock embedding provider."""
    provider = AsyncMock()
    provider.embed = AsyncMock(
        return_value=EmbeddingResponse(
            embeddings=[[0.1] * 384],
            model="test-model",
            total_tokens=10,
            latency_ms=50,
        )
    )
    provider.get_dimension = MagicMock(return_value=384)
    return provider
