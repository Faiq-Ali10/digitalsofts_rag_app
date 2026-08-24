"""Chat API endpoint — the main user-facing interaction.

POST /api/v1/chat — Send a message and get an AI response
GET  /api/v1/conversations — List user's conversations
GET  /api/v1/conversations/{id} — Get conversation with messages
POST /api/v1/feedback — Submit feedback on a response
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import run_agent
from app.agents.memory import (
    get_message_history,
    get_or_create_conversation,
    save_message,
    summarize_conversation_task,
)
from app.auth.dependencies import get_current_user
from app.core.schemas import APIResponse, PaginatedResponse
from app.db.models import (
    Conversation,
    Feedback,
    Message,
    MessageRole,
    ToolCall,
    ToolCallStatus,
    User,
)
from app.db.session import get_db

router = APIRouter(tags=["Chat"])
logger = structlog.get_logger(__name__)


# ── Schemas ──────────────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    """Chat message request."""

    message: str = Field(min_length=1, max_length=10000)
    conversation_id: uuid.UUID | None = None
    metadata_filters: dict | None = None
    stream: bool = False


class CitationResponse(BaseModel):
    index: int
    title: str
    source: str
    section: str | None = None
    page: str | None = None


class ToolCallResponse(BaseModel):
    id: uuid.UUID | None = None
    tool_name: str
    status: str
    requires_confirmation: bool = False


class ChatResponse(BaseModel):
    """Chat response with citations and diagnostics."""

    response: str
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    citations: list[CitationResponse] = []
    confidence: str
    tool_calls: list[ToolCallResponse] = []
    latency_ms: int = 0


class ConversationResponse(BaseModel):
    id: uuid.UUID
    title: str | None
    message_count: int
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    citations: list | None = None
    confidence: str | None = None
    created_at: str

    model_config = {"from_attributes": True}


class FeedbackRequest(BaseModel):
    message_id: uuid.UUID
    rating: int = Field(ge=1, le=5)
    comment: str | None = None


class ToolConfirmRequest(BaseModel):
    tool_call_id: uuid.UUID
    confirm: bool



# ── Chat Endpoint ────────────────────────────────────────────────────────────


@router.post("/chat", response_model=APIResponse[ChatResponse])
async def chat(
    body: ChatRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse[ChatResponse]:
    """Process a chat message through the AI agent.

    1. Create/get conversation
    2. Save user message
    3. Load conversation history
    4. Run agent workflow
    5. Save assistant response
    6. Return response with citations
    """
    # 1. Get or create conversation
    conv = await get_or_create_conversation(
        db, current_user.id, body.conversation_id
    )

    # 2. Save user message
    user_msg = await save_message(
        db, conv.id, MessageRole.USER, body.message
    )

    # 3. Load history
    history = await get_message_history(db, conv.id)

    # 4. Run agent
    state = await run_agent(
        query=body.message,
        conversation_id=str(conv.id),
        user_id=str(current_user.id),
        user_role=current_user.role.value,
        message_history=history[:-1],  # Exclude current message
        metadata_filters=body.metadata_filters,
    )

    # 5. Save assistant response
    citations_data = [
        {
            "index": c.index,
            "title": c.title,
            "source": c.source,
            "section": c.section,
            "page": c.page,
        }
        for c in state.citations
    ]

    assistant_msg = await save_message(
        db,
        conv.id,
        MessageRole.ASSISTANT,
        state.response,
        metadata=state.to_dict(),
        citations=citations_data,
        confidence=state.confidence,
        token_count=sum(
            u.get("completion_tokens", 0) + u.get("prompt_tokens", 0)
            for u in state.token_usage.values()
        ),
        latency_ms=state.latency_ms,
    )

    # Save tool calls if any
    saved_tool_calls = []
    for tc in state.tool_calls:
        tool_call = ToolCall(
            message_id=assistant_msg.id,
            tool_name=tc.tool_name,
            tool_input=tc.tool_input,
            tool_output=tc.tool_output,
            status=ToolCallStatus(tc.status),
        )
        db.add(tool_call)
        saved_tool_calls.append((tool_call, tc.requires_confirmation))

    await db.flush()

    # 5.5 Schedule summarization task
    background_tasks.add_task(summarize_conversation_task, conv.id)

    # 6. Build response
    return APIResponse(
        data=ChatResponse(
            response=state.response,
            conversation_id=conv.id,
            message_id=assistant_msg.id,
            citations=[
                CitationResponse(**c) for c in citations_data
            ],
            confidence=state.confidence,
            tool_calls=[
                ToolCallResponse(
                    id=tc.id,
                    tool_name=tc.tool_name,
                    status=tc.status.value,
                    requires_confirmation=req_conf,
                )
                for tc, req_conf in saved_tool_calls
            ],
            latency_ms=state.latency_ms,
        )
    )

# ── Tool Confirmation Endpoint ───────────────────────────────────────────────


@router.post("/chat/tool/confirm", response_model=APIResponse[ChatResponse])
async def confirm_tool(
    body: ToolConfirmRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse[ChatResponse]:
    """Confirm and execute a pending tool call."""
    from app.agents.nodes.actions import execute_action
    from app.agents.state import AgentState, ToolCallRecord

    # Fetch the pending tool call
    result = await db.execute(select(ToolCall).where(ToolCall.id == body.tool_call_id))
    tool_call = result.scalar_one_or_none()
    
    if not tool_call or tool_call.status != ToolCallStatus.PENDING:
        raise HTTPException(status_code=404, detail="Pending tool call not found")

    # Fetch the associated message and conversation
    msg_result = await db.execute(select(Message).where(Message.id == tool_call.message_id))
    msg = msg_result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    from app.agents.memory import get_message_history
    history = await get_message_history(db, msg.conversation_id)
    
    user_query = "User confirmed tool execution"
    for h in reversed(history):
        if h["role"] == "user":
            user_query = h["content"]
            break

    # Reconstruct state
    state = AgentState(
        query=user_query,
        conversation_id=str(msg.conversation_id),
        user_id=str(current_user.id),
        user_role=current_user.role.value,
        intent="action",
        message_history=history
    )

    tc_record = ToolCallRecord(
        tool_name=tool_call.tool_name,
        tool_input=tool_call.tool_input,
        status="approved" if body.confirm else "rejected",
    )
    state.tool_calls.append(tc_record)

    # Update DB status
    tool_call.status = ToolCallStatus.APPROVED if body.confirm else ToolCallStatus.REJECTED
    await db.commit()

    if not body.confirm:
        # Generate rejection response
        state.response = "I have canceled the action as requested."
        state.confidence = "supported"
    else:
        # Execute tool
        state = await execute_action(state)

        # Update DB with tool output
        tool_call.tool_output = tc_record.tool_output
        if tc_record.status == "executed":
            tool_call.status = ToolCallStatus.EXECUTED
        else:
            tool_call.status = ToolCallStatus.FAILED

    # Save new assistant message
    assistant_msg = await save_message(
        db,
        msg.conversation_id,
        MessageRole.ASSISTANT,
        state.response,
        metadata=state.to_dict(),
        confidence=state.confidence,
    )
    await db.commit()

    return APIResponse(
        data=ChatResponse(
            response=state.response,
            conversation_id=msg.conversation_id,
            message_id=assistant_msg.id,
            citations=[],
            confidence=state.confidence,
            tool_calls=[
                ToolCallResponse(
                    id=tool_call.id,
                    tool_name=tc_record.tool_name,
                    status=tc_record.status,
                    requires_confirmation=False,
                )
            ],
            latency_ms=state.latency_ms,
        )
    )
# ── Conversation Endpoints ───────────────────────────────────────────────────


@router.get("/conversations", response_model=APIResponse[list[ConversationResponse]])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse:
    """List the current user's conversations."""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
        .limit(50)
    )
    convs = result.scalars().all()

    return APIResponse(
        data=[
            ConversationResponse(
                id=c.id,
                title=c.title,
                message_count=c.message_count or 0,
                created_at=c.created_at.isoformat(),
                updated_at=c.updated_at.isoformat(),
            )
            for c in convs
        ]
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=APIResponse[list[MessageResponse]],
)
async def get_conversation(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse:
    """Get all messages in a conversation."""
    # Verify ownership
    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == current_user.id,
        )
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()

    return APIResponse(
        data=[
            MessageResponse(
                id=m.id,
                role=m.role.value,
                content=m.content,
                citations=m.citations,
                confidence=m.confidence,
                created_at=m.created_at.isoformat(),
            )
            for m in messages
        ]
    )


# ── Feedback Endpoint ────────────────────────────────────────────────────────


@router.post("/feedback", response_model=APIResponse[dict])
async def submit_feedback(
    body: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> APIResponse:
    """Submit feedback (thumbs up/down) on an assistant response."""
    # Verify message exists
    msg_result = await db.execute(select(Message).where(Message.id == body.message_id))
    msg = msg_result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    feedback = Feedback(
        message_id=body.message_id,
        user_id=current_user.id,
        rating=body.rating,
        comment=body.comment,
    )
    db.add(feedback)

    logger.info(
        "feedback_submitted",
        message_id=str(body.message_id),
        rating=body.rating,
        user_id=str(current_user.id),
    )

    return APIResponse(data={"status": "received"})
