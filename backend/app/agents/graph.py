"""LangGraph agent orchestrator — the core state machine.

Assembles all nodes into a directed graph with conditional edges.
This is the "brain" of the system — it controls what happens when.

State Machine:
  START → classify_intent
    ├─ blocked → END (injection response)
    ├─ knowledge → retrieve → evaluate → generate → verify → END
    │                            └─ rewrite (if poor) → retrieve (max 3 loops)
    ├─ structured → validate_action → execute → generate_tool_response → END
    ├─ action → validate_action → [confirm] → execute → END
    └─ unsupported → generate (I don't know) → END
"""

from __future__ import annotations

import time

import structlog

from app.agents.nodes.actions import execute_action, validate_action
from app.agents.nodes.classify_intent import classify_intent
from app.agents.nodes.knowledge import (
    evaluate_retrieval,
    generate_answer,
    retrieve_knowledge,
    rewrite_query,
    verify_response,
)
from app.agents.state import AgentState
from app.config import get_settings

try:
    from langfuse.decorators import langfuse_context, observe
except ImportError:
    # Dummy fallback if langfuse is not installed
    def observe(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    class _DummyContext:
        def update_current_trace(self, **kwargs):
            pass

    langfuse_context = _DummyContext()

logger = structlog.get_logger(__name__)


def _route_after_classify(state: AgentState) -> str:
    """Route based on classified intent."""
    intent = state.intent

    if intent == "blocked":
        return "end"
    elif intent == "knowledge":
        return "retrieve_knowledge"
    elif intent in ("structured", "action"):
        return "validate_action"
    elif intent == "unsupported":
        return "generate_unsupported"
    else:
        return "retrieve_knowledge"  # Default to knowledge


def _route_after_evaluate(state: AgentState) -> str:
    """Route based on retrieval evaluation."""
    if state.confidence == "supported":
        return "generate_answer"
    elif state.confidence == "unsupported" and not state.should_retry():
        return "generate_answer"  # Will say "I don't know"
    elif state.should_retry() and state.confidence != "supported":
        return "rewrite_query"
    else:
        return "generate_answer"


def _route_after_validate(state: AgentState) -> str:
    """Route based on action validation result."""
    if state.error or state.confidence == "unsupported":
        return "end"
    if state.pending_tool_confirmation:
        return "end"  # Waiting for user confirmation
    # Auto-approved tool — execute
    approved = any(tc.status == "approved" for tc in state.tool_calls)
    if approved:
        return "execute_action"
    return "end"


async def generate_unsupported(state: AgentState) -> AgentState:
    """Generate a response for unsupported questions."""
    state.current_node = "generate_unsupported"
    state.response = (
        "I appreciate your question, but it falls outside my area of expertise. "
        "I'm designed to help with Digitalsofts products, services, policies, "
        "and enterprise solutions. Here are some things I can help with:\n\n"
        "• Product information and comparisons\n"
        "• Feature details and specifications\n"
        "• Demo requests and sales inquiries\n"
        "• Support policies and implementation details\n"
        "• Technical FAQ\n\n"
        "How can I help you with our products or services?"
    )
    state.confidence = "unsupported"
    return state


@observe()
async def run_agent(
    query: str,
    conversation_id: str = "",
    user_id: str = "",
    user_role: str = "user",
    message_history: list[dict[str, str]] | None = None,
    metadata_filters: dict | None = None,
) -> AgentState:
    """Execute the agent workflow for a user query.

    This is the main entry point. It runs the state machine
    synchronously through all nodes until completion.

    Args:
        query: User's message.
        conversation_id: Session ID for conversation tracking.
        user_id: Authenticated user ID.
        user_role: User's role (admin/user).
        message_history: Previous messages in this conversation.
        metadata_filters: Optional retrieval filters.

    Returns:
        Final AgentState with response, citations, and diagnostics.
    """
    start_time = time.monotonic()

    state = AgentState(
        query=query,
        conversation_id=conversation_id,
        user_id=user_id,
        user_role=user_role,
        message_history=message_history or [],
        metadata_filters=metadata_filters or {},
    )

    if get_settings().langfuse_enabled:
        langfuse_context.update_current_trace(
            name="agent_workflow",
            session_id=conversation_id,
            user_id=user_id,
            tags=[user_role],
        )

    logger.info(
        "agent_workflow_started",
        query=query[:200],
        conversation_id=conversation_id,
        user_id=user_id,
    )

    try:
        # Step 0: Check for pending tool calls
        import uuid

        from sqlalchemy import select

        from app.db.models import Message, ToolCall, ToolCallStatus
        from app.db.session import async_session_factory

        is_confirmation = query.strip().lower() in (
            "confirm",
            "yes",
            "proceed",
            "y",
            "execute",
            "do it",
        )

        pending_tool = None
        if conversation_id and is_confirmation:
            async with async_session_factory() as session:
                try:
                    conv_uuid = uuid.UUID(conversation_id)
                    result = await session.execute(
                        select(ToolCall)
                        .join(Message, Message.id == ToolCall.message_id)
                        .where(Message.conversation_id == conv_uuid)
                        .where(ToolCall.status == ToolCallStatus.PENDING)
                        .order_by(ToolCall.created_at.desc())
                        .limit(1)
                    )
                    pending_tool = result.scalar_one_or_none()
                except Exception:
                    pass

        if pending_tool:
            # Bypass intent classifier and route directly to execute
            state.intent = "action"
            from app.agents.state import ToolCallRecord

            tc_record = ToolCallRecord(
                tool_name=pending_tool.tool_name,
                tool_input=pending_tool.tool_input,
                status="approved",
            )
            state.tool_calls.append(tc_record)
            route = "execute_action"
        else:
            # Step 1: Classify intent
            state = await classify_intent(state)
            # Route based on intent
            route = _route_after_classify(state)

        if route == "end":
            # Blocked or already has response
            pass

        elif route == "retrieve_knowledge":
            # RAG pipeline with retry loop
            state = await retrieve_knowledge(state)
            state = await evaluate_retrieval(state)

            eval_route = _route_after_evaluate(state)

            while eval_route == "rewrite_query" and state.iteration_count < state.max_iterations:
                state.iteration_count += 1
                state = await rewrite_query(state)
                state = await retrieve_knowledge(state)
                state = await evaluate_retrieval(state)
                eval_route = _route_after_evaluate(state)

            state = await generate_answer(state)
            state = await verify_response(state)

        elif route == "validate_action":
            state = await validate_action(state)

            action_route = _route_after_validate(state)

            if action_route == "execute_action":
                state = await execute_action(state)

        elif route == "execute_action":
            state = await execute_action(state)
            if pending_tool:
                async with async_session_factory() as session:
                    result = await session.execute(
                        select(ToolCall).where(ToolCall.id == pending_tool.id)
                    )
                    db_tool = result.scalar_one_or_none()
                    if db_tool:
                        executed_record = next(
                            (tc for tc in state.tool_calls if tc.tool_name == db_tool.tool_name),
                            None,
                        )
                        if executed_record and executed_record.status == "executed":
                            db_tool.status = ToolCallStatus.EXECUTED
                            db_tool.tool_output = executed_record.tool_output
                        else:
                            db_tool.status = ToolCallStatus.FAILED
                            if executed_record:
                                db_tool.error = getattr(
                                    executed_record, "error", str(executed_record.error)
                                )
                        await session.commit()

        elif route == "generate_unsupported":
            state = await generate_unsupported(state)

    except Exception as e:
        logger.error(
            "agent_workflow_error",
            error=str(e),
            node=state.current_node,
            exc_info=True,
        )
        state.error = str(e)
        state.response = (
            "I apologize, but I encountered an unexpected error. Please try again in a moment."
        )
        state.confidence = "unsupported"

    # Record total latency
    state.latency_ms = int((time.monotonic() - start_time) * 1000)

    logger.info(
        "agent_workflow_completed",
        intent=state.intent,
        confidence=state.confidence,
        iterations=state.iteration_count,
        latency_ms=state.latency_ms,
        error=state.error,
    )

    return state
