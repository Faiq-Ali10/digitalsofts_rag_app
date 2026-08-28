"""Conversation memory management.

Implements a sliding window strategy with summarization:
- Short-term: Last N messages loaded directly
- Summarization: Older messages compressed into a summary
- Token budget: Max tokens allocated for conversation context
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message, MessageRole

logger = structlog.get_logger(__name__)

# Memory configuration
MAX_RECENT_MESSAGES = 10  # Keep last 10 messages in full
MAX_HISTORY_TOKENS = 2000  # Token budget for conversation history
SUMMARY_THRESHOLD = 15  # Summarize when message count exceeds this


async def get_or_create_conversation(
    db: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID | None = None,
) -> Conversation:
    """Get an existing conversation or create a new one."""
    if conversation_id:
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        conv = result.scalar_one_or_none()
        if conv:
            return conv

    # Create new conversation
    conv = Conversation(user_id=user_id)
    db.add(conv)
    await db.flush()
    return conv


async def get_message_history(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    max_messages: int = MAX_RECENT_MESSAGES,
) -> list[dict[str, str]]:
    """Retrieve recent message history for context.

    Returns the last N messages as role/content dicts suitable
    for passing to the LLM.
    """
    # Fetch summary
    summary_result = await db.execute(
        select(Conversation.summary).where(Conversation.id == conversation_id)
    )
    summary = summary_result.scalar_one_or_none()

    # Fetch messages
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(max_messages)
    )
    messages = list(reversed(result.scalars().all()))

    history = []
    if summary:
        history.append({"role": "system", "content": f"Previous conversation summary: {summary}"})

    history.extend([{"role": msg.role.value, "content": msg.content} for msg in messages])

    return history


async def save_message(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    role: MessageRole,
    content: str,
    metadata: dict | None = None,
    citations: list | None = None,
    confidence: str | None = None,
    token_count: int | None = None,
    latency_ms: int | None = None,
) -> Message:
    """Save a message to the conversation."""
    msg = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        metadata_=metadata,
        citations=citations,
        confidence=confidence,
        token_count=token_count,
        latency_ms=latency_ms,
    )
    db.add(msg)

    # Update conversation message count and title
    conv_result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    conv = conv_result.scalar_one_or_none()
    if conv:
        conv.message_count = (conv.message_count or 0) + 1
        # Auto-title from first user message
        if not conv.title and role == MessageRole.USER:
            conv.title = content[:100] + ("..." if len(content) > 100 else "")

    await db.flush()
    return msg


async def should_summarize(
    db: AsyncSession,
    conversation_id: uuid.UUID,
) -> bool:
    """Check if conversation needs summarization."""
    result = await db.execute(
        select(func.count()).where(Message.conversation_id == conversation_id)
    )
    count = result.scalar() or 0
    return count > SUMMARY_THRESHOLD


async def get_conversation_summary(
    db: AsyncSession,
    conversation_id: uuid.UUID,
) -> str | None:
    """Get the stored conversation summary."""
    result = await db.execute(
        select(Conversation.summary).where(Conversation.id == conversation_id)
    )
    return result.scalar_one_or_none()


async def update_conversation_summary(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    summary: str,
) -> None:
    """Store a conversation summary."""
    result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    conv = result.scalar_one_or_none()
    if conv:
        conv.summary = summary
        await db.flush()


async def summarize_conversation_task(conversation_id: uuid.UUID) -> None:
    """Background task to summarize a conversation."""
    from app.db.session import async_session_factory
    from app.llm.litellm_provider import get_llm_provider

    logger.info("starting_summarization", conversation_id=str(conversation_id))

    db = async_session_factory()
    try:
        # Check if we actually need to summarize
        if not await should_summarize(db, conversation_id):
            return

        # Get full history to summarize (up to last 20 messages)
        history = await get_message_history(db, conversation_id, max_messages=20)

        if not history:
            return

        # Prepare LLM request
        llm = get_llm_provider()
        history_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in history])

        response = await llm.complete(
            messages=[
                {
                    "role": "system",
                    "content": "Summarize the following conversation concisely. Focus on the user's main goals, key facts established, and any pending actions. Do not exceed 200 words.",
                },
                {"role": "user", "content": history_text},
            ],
            temperature=0.1,
            max_tokens=300,
        )

        summary = response.content.strip()
        await update_conversation_summary(db, conversation_id, summary)
        await db.commit()

        logger.info("summarization_completed", conversation_id=str(conversation_id))

    except Exception as e:
        logger.error("summarization_failed", conversation_id=str(conversation_id), error=str(e))
        await db.rollback()
    finally:
        await db.close()
