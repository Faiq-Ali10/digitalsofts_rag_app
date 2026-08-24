"""LiteLLM-based LLM provider implementation.

Supports Gemini (primary) and Groq (fallback) through LiteLLM's
unified API. Includes retry with exponential backoff, timeout
handling, and circuit breaker pattern.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator  # noqa: TC003

import structlog
from litellm import acompletion

from app.config import get_settings
from app.llm.provider import LLMProvider, LLMResponse

settings = get_settings()
logger = structlog.get_logger(__name__)


class CircuitBreaker:
    """Simple circuit breaker to avoid hammering a failing provider.

    After `failure_threshold` consecutive failures, the circuit opens
    and all requests fail-fast for `recovery_timeout` seconds.
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time: float = 0
        self.is_open = False

    def record_success(self) -> None:
        self.failure_count = 0
        self.is_open = False

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.failure_count >= self.failure_threshold:
            self.is_open = True
            logger.warning(
                "circuit_breaker_opened",
                failure_count=self.failure_count,
            )

    def can_execute(self) -> bool:
        if not self.is_open:
            return True
        # Check if recovery timeout has elapsed
        elapsed = time.monotonic() - self.last_failure_time
        if elapsed >= self.recovery_timeout:
            logger.info("circuit_breaker_half_open", elapsed_seconds=elapsed)
            return True  # Allow a test request
        return False


class LiteLLMProvider(LLMProvider):
    """LLM provider using LiteLLM for multi-provider support.

    Primary: Gemini (via GEMINI_API_KEY)
    Fallback: Groq (via GROQ_API_KEY)
    """

    def __init__(
        self,
        primary_model: str | None = None,
        fallback_model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
    ):
        self.primary_model = primary_model or settings.llm_primary_model
        self.fallback_model = fallback_model or settings.llm_fallback_model
        self.default_temperature = temperature if temperature is not None else settings.llm_temperature  # noqa: E501
        self.default_max_tokens = max_tokens or settings.llm_max_tokens
        self.timeout = timeout or settings.llm_timeout_seconds
        self.max_retries = max_retries if max_retries is not None else settings.llm_max_retries

        self.primary_circuit = CircuitBreaker()
        self.fallback_circuit = CircuitBreaker()

        # Set API keys as environment variables for LiteLLM
        import os
        if settings.gemini_api_key:
            os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
        if settings.groq_api_key:
            os.environ["GROQ_API_KEY"] = settings.groq_api_key

        # Configure Langfuse callbacks
        if settings.langfuse_enabled:
            import litellm
            os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key
            os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key
            os.environ["LANGFUSE_HOST"] = settings.langfuse_host
            if "langfuse" not in litellm.success_callback:
                litellm.success_callback.append("langfuse")
            if "langfuse" not in litellm.failure_callback:
                litellm.failure_callback.append("langfuse")

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
        """Generate a completion with automatic fallback.

        Tries primary model first. On failure, retries with exponential
        backoff. If primary circuit is open, falls back to secondary.
        """
        temp = temperature if temperature is not None else self.default_temperature
        tokens = max_tokens or self.default_max_tokens

        # Try primary model
        if self.primary_circuit.can_execute():
            try:
                return await self._call_with_retry(
                    model=self.primary_model,
                    messages=messages,
                    temperature=temp,
                    max_tokens=tokens,
                    response_format=response_format,
                    stop=stop,
                    circuit=self.primary_circuit,
                    metadata=metadata,
                )
            except Exception as e:
                logger.warning(
                    "primary_model_failed",
                    model=self.primary_model,
                    error=str(e),
                )

        # Try fallback model
        if self.fallback_model and self.fallback_circuit.can_execute():
            logger.info("falling_back_to_secondary", model=self.fallback_model)
            try:
                return await self._call_with_retry(
                    model=self.fallback_model,
                    messages=messages,
                    temperature=temp,
                    max_tokens=tokens,
                    response_format=response_format,
                    stop=stop,
                    circuit=self.fallback_circuit,
                    metadata=metadata,
                )
            except Exception as e:
                logger.error(
                    "fallback_model_failed",
                    model=self.fallback_model,
                    error=str(e),
                )
                raise

        raise RuntimeError(
            "All LLM providers are unavailable. "
            f"Primary ({self.primary_model}) and fallback ({self.fallback_model}) "
            "circuits are open."
        )

    async def _call_with_retry(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: dict | None,
        stop: list | None,
        circuit: CircuitBreaker,
        metadata: dict | None = None,
    ) -> LLMResponse:
        """Call LiteLLM with exponential backoff retry."""
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                start = time.monotonic()

                kwargs: dict = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "timeout": self.timeout,
                }
                if response_format:
                    kwargs["response_format"] = response_format
                if stop:
                    kwargs["stop"] = stop
                if metadata:
                    kwargs["metadata"] = metadata

                response = await acompletion(**kwargs)
                latency_ms = int((time.monotonic() - start) * 1000)

                circuit.record_success()

                usage = response.usage or {}
                result = LLMResponse(
                    content=response.choices[0].message.content or "",
                    model=model,
                    prompt_tokens=getattr(usage, "prompt_tokens", 0),
                    completion_tokens=getattr(usage, "completion_tokens", 0),
                    total_tokens=getattr(usage, "total_tokens", 0),
                    latency_ms=latency_ms,
                    finish_reason=response.choices[0].finish_reason or "stop",
                )

                logger.info(
                    "llm_completion",
                    model=model,
                    tokens=result.total_tokens,
                    latency_ms=latency_ms,
                    cost=f"${result.cost_estimate:.6f}",
                )

                return result

            except Exception as e:
                last_error = e
                circuit.record_failure()

                if attempt < self.max_retries:
                    backoff = min(2 ** attempt, 16)  # 1, 2, 4, 8, 16 max
                    logger.warning(
                        "llm_retry",
                        model=model,
                        attempt=attempt + 1,
                        backoff_seconds=backoff,
                        error=str(e),
                    )
                    await asyncio.sleep(backoff)

        raise last_error  # type: ignore[misc]

    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        metadata: dict | None = None,
    ) -> AsyncIterator[str]:
        """Stream completion tokens from the primary model."""
        temp = temperature if temperature is not None else self.default_temperature
        tokens = max_tokens or self.default_max_tokens

        model = self.primary_model
        if not self.primary_circuit.can_execute():
            model = self.fallback_model

        import os
        if settings.gemini_api_key:
            os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
        if settings.groq_api_key:
            os.environ["GROQ_API_KEY"] = settings.groq_api_key

        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": tokens,
            "timeout": self.timeout,
            "stream": True,
        }
        if metadata:
            kwargs["metadata"] = metadata

        response = await acompletion(**kwargs)

        async for chunk in response:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    async def health_check(self) -> bool:
        """Check if at least one provider is reachable."""
        try:
            await self.complete(
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            return True
        except Exception:
            return False


# ── Factory ──────────────────────────────────────────────────────────────────

_provider_instance: LiteLLMProvider | None = None


def get_llm_provider() -> LiteLLMProvider:
    """Get or create the singleton LLM provider instance."""
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = LiteLLMProvider()
    return _provider_instance
