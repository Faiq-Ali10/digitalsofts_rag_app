"""Intent classification node.

Classifies user queries into one of:
- knowledge: answerable from the knowledge base
- structured: requires structured data query (product search)
- action: requires tool execution (demo request, etc.)
- unsupported: cannot be answered by the system
- blocked: prompt injection or policy violation detected
"""

from __future__ import annotations

import json
import re

import structlog

from app.agents.state import AgentState
from app.llm.litellm_provider import get_llm_provider

logger = structlog.get_logger(__name__)

# Known injection patterns (checked BEFORE LLM classification)
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"ignore\s+your\s+(rules|guidelines|policies|instructions|knowledge\s+base)",
    r"you\s+are\s+now\s+(an?\s+)?admin",
    r"reveal\s+(your\s+)?(system\s+)?prompt",
    r"what\s+are\s+your\s+(system\s+)?instructions",
    r"override\s+(your\s+)?(system\s+)?(policy|instructions)",
    r"pretend\s+you\s+are",
    r"act\s+as\s+(if\s+)?you\s+are",
    r"DAN\s+mode",
    r"jailbreak",
    r"translate\s+the\s+system\s+prompt",
    r"(?:DROP|DELETE|TRUNCATE|ALTER)\s+(?:TABLE|DATABASE)",
]

CLASSIFICATION_PROMPT = """You are an intent classifier for an enterprise AI assistant.

Classify the user's query into exactly ONE of these categories:

1. "knowledge" — The user is asking a general question that can be answered from product documentation, FAQs, policies, or company knowledge base (e.g., "How does X work?", "What is the return policy?"). Do NOT use this if the user is asking to search for products.
2. "structured" — The user wants to search for, list, or compare specific products/services by name, feature, or category (e.g., "Search your products for X", "What products do you have for Y").
3. "action" — The user wants to perform an action: request a demo, create a ticket, contact sales, schedule a meeting.
4. "unsupported" — The query is outside the scope of the enterprise assistant (personal questions, general trivia, coding help, etc.).

Respond with ONLY a JSON object:
{
    "intent": "knowledge" | "structured" | "action" | "unsupported",
    "confidence": 0.0 to 1.0,
    "reasoning": "brief explanation"
}

User query: """


async def classify_intent(state: AgentState) -> AgentState:
    """Classify the user's intent and detect prompt injection.

    This is the first node in the workflow. It runs two checks:
    1. Pattern-based injection detection (fast, no LLM cost)
    2. LLM-based intent classification

    If injection is detected, the workflow routes to the security
    block state instead of proceeding normally.
    """
    state.current_node = "classify_intent"
    query = state.query

    # 1. Pattern-based injection check (pre-LLM)
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, query, re.IGNORECASE):
            logger.warning(
                "injection_detected_pattern",
                pattern=pattern,
                query=query[:200],
                user_id=state.user_id,
            )
            state.intent = "blocked"
            state.injection_detected = True
            state.response = (
                "I'm designed to help with Digitalsofts products, services, "
                "and enterprise solutions. I can't process that type of request. "
                "How can I help you with our products or services?"
            )
            state.confidence = "blocked"
            return state

    # 2. LLM-based classification
    try:
        llm = get_llm_provider()
        response = await llm.complete(
            messages=[
                {
                    "role": "system",
                    "content": "You are an intent classifier. Respond with JSON only.",
                },
                {
                    "role": "user",
                    "content": CLASSIFICATION_PROMPT + query,
                },
            ],
            temperature=0.0,
            max_tokens=200,
            response_format={"type": "json_object"},
        )

        # Parse JSON response
        content = response.content.strip()
        # Handle markdown code blocks
        if content.startswith("```"):
            # Strip the first line (e.g., ```json) and the last line (```)
            content = "\n".join(content.split("\n")[1:-1])
            content = content.strip()

        result = json.loads(content)

        state.intent = result.get("intent", "unsupported")
        state.intent_confidence = float(result.get("confidence", 0.5))

        # Track token usage
        state.token_usage["classify"] = {
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
        }

        logger.info(
            "intent_classified",
            intent=state.intent,
            confidence=state.intent_confidence,
            reasoning=result.get("reasoning", ""),
        )

    except Exception as e:
        logger.error("classification_failed", error=str(e), raw_content=content if 'content' in locals() else 'None')
        # Default to knowledge question on classification failure
        state.intent = "knowledge"
        state.intent_confidence = 0.3

    return state
