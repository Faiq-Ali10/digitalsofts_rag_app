"""LLM provider abstraction layer.

Defines the interface that all LLM providers must implement.
The application interacts ONLY through this interface — never
directly with Gemini, Groq, or any specific provider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider."""

    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0
    finish_reason: str = "stop"
    raw_response: dict = field(default_factory=dict)

    @property
    def cost_estimate(self) -> float:
        """Rough cost estimate based on token usage.

        These are approximations — actual costs depend on the provider.
        """
        # Approximate costs per 1M tokens (input/output)
        cost_map = {
            "gemini/gemini-3.6-flash": (0.075, 0.30),
            "groq/llama-3.1-70b-versatile": (0.59, 0.79),
        }
        input_rate, output_rate = cost_map.get(self.model, (0.5, 1.5))
        return (
            (self.prompt_tokens * input_rate / 1_000_000)
            + (self.completion_tokens * output_rate / 1_000_000)
        )


@dataclass
class EmbeddingResponse:
    """Standardized response from an embedding provider."""

    embeddings: list[list[float]]
    model: str
    total_tokens: int = 0
    latency_ms: int = 0


class LLMProvider(ABC):
    """Abstract interface for LLM providers.

    All agent nodes and RAG components interact with this interface,
    not with any specific provider. This enables switching providers
    without changing business logic.
    """

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        stop: list[str] | None = None,
        metadata: dict | None = None,
    ) -> LLMResponse:
        """Generate a completion from the LLM.

        Args:
            messages: List of {"role": ..., "content": ...} message dicts.
            temperature: Sampling temperature (0.0 = deterministic).
            max_tokens: Maximum tokens in the response.
            response_format: Structured output format (JSON schema).
            stop: Stop sequences.

        Returns:
            Standardized LLMResponse.
        """
        ...

    @abstractmethod
    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        metadata: dict | None = None,
    ) -> AsyncIterator[str]:
        """Stream a completion token-by-token.

        Yields individual text chunks as they arrive.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the provider is available and responding."""
        ...


class EmbeddingProvider(ABC):
    """Abstract interface for embedding providers.

    Separated from LLMProvider because embeddings may use
    a different provider (e.g., local sentence-transformers).
    """

    @abstractmethod
    async def embed(self, texts: list[str]) -> EmbeddingResponse:
        """Generate embeddings for a list of texts.

        Args:
            texts: List of text strings to embed.

        Returns:
            EmbeddingResponse with vectors matching input order.
        """
        ...

    @abstractmethod
    def get_dimension(self) -> int:
        """Return the embedding dimension for this model."""
        ...
