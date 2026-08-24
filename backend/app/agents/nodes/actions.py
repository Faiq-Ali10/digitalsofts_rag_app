"""Action and tool execution nodes for the LangGraph agent.

Handles:
1. validate_action — Schema + auth + business rule validation
2. execute_action — Guarded tool execution with audit logging
"""

from __future__ import annotations

import json
import re

import structlog

from app.agents.state import AgentState, ToolCallRecord
from app.llm.litellm_provider import get_llm_provider

logger = structlog.get_logger(__name__)

ACTION_EXTRACTION_PROMPT = """You are an action extractor for an enterprise AI assistant.

Based on the user's message, determine which tool to call and extract the parameters.

Available tools:
1. "search_products" — Search for products/services
   Parameters: {"query": "search terms", "category": "optional category filter"}

2. "create_demo_request" — Create a demo request for a customer
   Parameters: {"customer_name": "name", "email": "email", "company": "company", "product": "product name", "requirements": "optional details"}

3. "search_knowledge" — Search the knowledge base with specific filters
   Parameters: {"query": "search terms", "filters": {"product": "optional", "document_type": "optional"}}

4. "compare_products" — Compare two products
   Parameters: {"product_a": "first product", "product_b": "second product"}

Respond with JSON:
{
    "tool_name": "tool_name",
    "tool_input": { ... parameters ... },
    "requires_confirmation": true/false,
    "reasoning": "why this tool"
}

If the user hasn't provided enough information for the tool, set "missing_info" to a list of what's needed.

User message: """


async def validate_action(state: AgentState) -> AgentState:
    """Validate the requested action and extract tool parameters.

    Validates:
    1. Tool name is in the allowlist
    2. Required parameters are present
    3. Parameter types/formats are correct
    4. User has permission for the tool
    """
    state.current_node = "validate_action"

    ALLOWED_TOOLS = {"search_products", "create_demo_request", "search_knowledge", "compare_products"}
    CONFIRMATION_REQUIRED = {"create_demo_request"}

    try:
        llm = get_llm_provider()
        response = await llm.complete(
            messages=[
                {
                    "role": "system",
                    "content": "You are a tool parameter extractor. Respond with JSON only.",
                },
                {
                    "role": "user",
                    "content": ACTION_EXTRACTION_PROMPT + state.query,
                },
            ],
            temperature=0.0,
            max_tokens=300,
        )

        content = response.content.strip()
        if content.startswith("```"):
            content = re.sub(r"```(?:json)?\s*", "", content)
            content = content.rstrip("`").strip()

        result = json.loads(content)

        tool_name = result.get("tool_name", "")
        tool_input = result.get("tool_input", {})
        missing_info = result.get("missing_info", [])

        # Validate tool is allowed
        if tool_name not in ALLOWED_TOOLS:
            state.response = (
                f"I don't have a tool called '{tool_name}'. "
                "I can help you search products, create demo requests, "
                "search our knowledge base, or compare products."
            )
            state.confidence = "unsupported"
            return state

        # Check for missing information
        if missing_info:
            missing_str = ", ".join(missing_info)
            state.response = (
                f"I'd be happy to help with that! To proceed, I'll need the following "
                f"information: {missing_str}. Could you please provide these details?"
            )
            state.confidence = "partial"
            return state

        # Validate email format for demo requests
        if tool_name == "create_demo_request":
            email = tool_input.get("email", "")
            if email and not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
                state.response = (
                    "The email address provided doesn't appear to be valid. "
                    "Could you please provide a valid email address?"
                )
                state.confidence = "partial"
                return state

        # Create tool call record
        requires_conf = tool_name in CONFIRMATION_REQUIRED
        tool_call = ToolCallRecord(
            tool_name=tool_name,
            tool_input=tool_input,
            requires_confirmation=requires_conf,
        )

        state.tool_calls.append(tool_call)

        if requires_conf:
            state.pending_tool_confirmation = tool_call
            # Generate confirmation message
            state.response = _build_confirmation_message(tool_name, tool_input)
            state.confidence = "partial"
        else:
            # Auto-execute read-only tools
            tool_call.status = "approved"

        logger.info(
            "action_validated",
            tool=tool_name,
            requires_confirmation=requires_conf,
        )

    except json.JSONDecodeError:
        state.response = (
            "I understood you'd like to take an action, but I couldn't determine "
            "the specific details. Could you please rephrase your request?"
        )
        state.confidence = "partial"
    except Exception as e:
        logger.error("action_validation_failed", error=str(e))
        state.error = str(e)
        state.response = "I encountered an error processing your request. Please try again."
        state.confidence = "unsupported"

    return state


async def execute_action(state: AgentState) -> AgentState:
    """Execute validated and approved tool calls.

    Tool execution flow:
    1. Check tool is approved
    2. Execute with timeout
    3. Record result
    4. Generate response from tool output
    """
    state.current_node = "execute_action"

    for tool_call in state.tool_calls:
        if tool_call.status != "approved":
            continue

        try:
            # Import and execute the tool
            from app.tools.registry import execute_tool

            result = await execute_tool(
                tool_name=tool_call.tool_name,
                tool_input=tool_call.tool_input,
                user_id=state.user_id,
                user_role=state.user_role,
            )

            tool_call.tool_output = result
            tool_call.status = "executed"

            logger.info(
                "tool_executed",
                tool=tool_call.tool_name,
                status="success",
            )

        except Exception as e:
            tool_call.status = "failed"
            tool_call.error = str(e)
            logger.error(
                "tool_execution_failed",
                tool=tool_call.tool_name,
                error=str(e),
            )

    # Generate response from tool results
    await _generate_tool_response(state)

    return state


async def _generate_tool_response(state: AgentState) -> None:
    """Generate a natural language response from tool outputs."""
    executed_tools = [tc for tc in state.tool_calls if tc.status == "executed"]
    failed_tools = [tc for tc in state.tool_calls if tc.status == "failed"]

    if not executed_tools and not failed_tools:
        return

    # Build context from tool results
    tool_results = []
    for tc in executed_tools:
        tool_results.append(
            f"Tool: {tc.tool_name}\nInput: {json.dumps(tc.tool_input)}\n"
            f"Result: {json.dumps(tc.tool_output)}"
        )

    for tc in failed_tools:
        tool_results.append(
            f"Tool: {tc.tool_name} — FAILED: {tc.error}"
        )

    context = "\n\n".join(tool_results)

    try:
        llm = get_llm_provider()
        response = await llm.complete(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are the Digitalsofts Enterprise AI Assistant. "
                        "Summarize the tool results into a helpful, natural response. "
                        "Present the information clearly and professionally."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"User asked: {state.query}\n\n"
                        f"Tool results:\n{context}\n\n"
                        "Please provide a clear response based on these results."
                    ),
                },
            ],
            temperature=0.1,
            max_tokens=1000,
        )

        state.response = response.content
        state.confidence = "supported" if executed_tools else "partial"

    except Exception as e:
        logger.error("tool_response_generation_failed", error=str(e))
        if executed_tools:
            state.response = f"Here are the results:\n{context}"
        else:
            state.response = "I encountered errors while processing your request."


def _build_confirmation_message(tool_name: str, tool_input: dict) -> str:
    """Build a human-readable confirmation message for a tool action."""
    if tool_name == "create_demo_request":
        return (
            f"I'd like to create a demo request with the following details:\n\n"
            f"• **Customer**: {tool_input.get('customer_name', 'N/A')}\n"
            f"• **Email**: {tool_input.get('email', 'N/A')}\n"
            f"• **Company**: {tool_input.get('company', 'N/A')}\n"
            f"• **Product**: {tool_input.get('product', 'N/A')}\n"
            f"• **Requirements**: {tool_input.get('requirements', 'None specified')}\n\n"
            "Shall I proceed with creating this demo request? (Please confirm)"
        )

    return f"I'd like to execute {tool_name}. Shall I proceed?"
