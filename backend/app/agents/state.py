"""Agent state definition for the LangGraph orchestrator.

Typed state ensures every node receives and produces well-defined data.
This prevents uncontrolled state mutations and makes the agent debuggable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.retrieval.retriever import RetrievedChunk


@dataclass
class Citation:
    """A source citation for a generated answer."""

    index: int
    title: str
    source: str
    section: str | None = None
    page: str | None = None
    chunk_id: str | None = None


@dataclass
class ToolCallRecord:
    """Record of a tool invocation within the agent workflow."""

    tool_name: str
    tool_input: dict
    tool_output: dict | None = None
    status: str = "pending"  # pending, approved, executed, failed, rejected
    requires_confirmation: bool = False
    error: str | None = None


@dataclass
class AgentState:
    """Complete state of the agent workflow.

    This is passed through all LangGraph nodes. Each node reads
    what it needs and updates specific fields. The state machine
    ensures controlled transitions between states.
    """

    # ── Input ────────────────────────────────────────────────────────────
    query: str = ""
    conversation_id: str = ""
    user_id: str = ""
    user_role: str = "user"
    message_history: list[dict[str, str]] = field(default_factory=list)

    # ── Intent Classification ────────────────────────────────────────────
    intent: Literal["knowledge", "structured", "action", "unsupported", "blocked", "pending"] = (
        "pending"
    )
    intent_confidence: float = 0.0
    injection_detected: bool = False

    # ── Retrieval ────────────────────────────────────────────────────────
    retrieved_chunks: list[RetrievedChunk] = field(default_factory=list)
    retrieval_score: float = 0.0
    retrieval_query: str = ""
    metadata_filters: dict = field(default_factory=dict)

    # ── Tool Execution ───────────────────────────────────────────────────
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    pending_tool_confirmation: ToolCallRecord | None = None

    # ── Generation ───────────────────────────────────────────────────────
    response: str = ""
    citations: list[Citation] = field(default_factory=list)
    confidence: Literal["supported", "partial", "unsupported", "blocked"] = "unsupported"

    # ── Control Flow ─────────────────────────────────────────────────────
    iteration_count: int = 0
    max_iterations: int = 3
    error: str | None = None
    current_node: str = "start"

    # ── Diagnostics ──────────────────────────────────────────────────────
    latency_ms: int = 0
    token_usage: dict = field(default_factory=dict)

    def should_retry(self) -> bool:
        """Check if we can retry retrieval."""
        return self.iteration_count < self.max_iterations

    def to_dict(self) -> dict:
        """Serialize state for logging/storage (excluding large fields)."""
        return {
            "query": self.query[:200],
            "intent": self.intent,
            "confidence": self.confidence,
            "iteration_count": self.iteration_count,
            "retrieved_chunks": len(self.retrieved_chunks),
            "tool_calls": len(self.tool_calls),
            "error": self.error,
            "current_node": self.current_node,
        }
