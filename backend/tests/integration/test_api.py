"""Integration tests for API routes."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def async_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_health_check(async_client: AsyncClient):
    response = await async_client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_unauthorized_chat_access(async_client: AsyncClient):
    # Without auth header
    response = await async_client.post("/api/v1/chat", json={"message": "Hello"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_chat_message(async_client: AsyncClient, mock_user, monkeypatch):
    import uuid
    from unittest.mock import AsyncMock

    from app.agents.state import AgentState
    from app.auth.dependencies import get_current_user
    from app.db.models import Conversation, Message
    from app.db.session import get_db

    # Mock the auth and db dependency
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: AsyncMock()

    # Mock database helper functions in chat.py
    async def mock_get_or_create_conversation(*args, **kwargs):
        return Conversation(id=uuid.uuid4(), user_id=mock_user.id)

    async def mock_save_message(*args, **kwargs):
        return Message(id=uuid.uuid4(), conversation_id=uuid.uuid4())

    async def mock_get_message_history(*args, **kwargs):
        return []

    monkeypatch.setattr(
        "app.api.v1.chat.get_or_create_conversation", mock_get_or_create_conversation
    )  # noqa: E501
    monkeypatch.setattr("app.api.v1.chat.save_message", mock_save_message)
    monkeypatch.setattr("app.api.v1.chat.get_message_history", mock_get_message_history)  # noqa: E501

    # Mock the run_agent function instead of executing full graph
    async def mock_run_agent(*args, **kwargs):
        state = AgentState(query=kwargs.get("query", ""))
        state.response = "Hello from mock agent"
        state.confidence = "supported"
        state.latency_ms = 100
        return state

    monkeypatch.setattr("app.api.v1.chat.run_agent", mock_run_agent)

    response = await async_client.post("/api/v1/chat", json={"message": "Hello"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["response"] == "Hello from mock agent"
    assert data["confidence"] == "supported"

    # Cleanup overrides
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_unauthorized_documents_access(async_client: AsyncClient):
    response = await async_client.get("/api/v1/documents")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_documents_admin_upload(async_client: AsyncClient, mock_admin_user, monkeypatch):
    from app.auth.dependencies import get_current_user

    app.dependency_overrides[get_current_user] = lambda: mock_admin_user

    # We'll just test that it reaches the endpoint and errors out with 400 because of missing file
    # rather than full upload mechanics which are complex to mock here.
    # Actually, if we send no file, it's a 422 Validation Error.
    response = await async_client.post("/api/v1/documents")
    assert response.status_code == 422

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_documents_user_upload_forbidden(async_client: AsyncClient, mock_user):
    from app.auth.dependencies import get_current_user

    app.dependency_overrides[get_current_user] = lambda: mock_user

    response = await async_client.post("/api/v1/documents")
    assert response.status_code == 403

    app.dependency_overrides.clear()
