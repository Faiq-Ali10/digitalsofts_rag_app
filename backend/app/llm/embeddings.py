"""Local embedding provider using sentence-transformers.

Runs embeddings on-device — no external API calls needed.
The model is loaded once and reused across all requests.
"""

from __future__ import annotations

import asyncio
import time
from functools import lru_cache

import structlog

from app.config import get_settings
from app.llm.provider import EmbeddingProvider, EmbeddingResponse

settings = get_settings()
logger = structlog.get_logger(__name__)


class SentenceTransformerEmbedder(EmbeddingProvider):
    """Embedding provider using sentence-transformers (local inference).

    Default model: all-MiniLM-L6-v2 (384 dimensions, fast, good quality).
    The model can be swapped via EMBEDDING_MODEL_NAME env var.
    """

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or settings.embedding_model_name
        self._model = None
        self._dimension = settings.embedding_dimension

    def _get_model(self):
        """Lazy-load the sentence-transformers model."""
        if self._model is None:
            logger.info("loading_embedding_model", model=self.model_name)
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
            # Update dimension from actual model
            self._dimension = self._model.get_sentence_embedding_dimension()
            logger.info(
                "embedding_model_loaded",
                model=self.model_name,
                dimension=self._dimension,
            )
        return self._model

    async def embed(self, texts: list[str]) -> EmbeddingResponse:
        """Generate embeddings using local sentence-transformers model.

        Runs the model in a thread pool to avoid blocking the event loop.
        """
        if not texts:
            return EmbeddingResponse(
                embeddings=[],
                model=self.model_name,
            )

        start = time.monotonic()

        # Run CPU-bound embedding in thread pool
        loop = asyncio.get_event_loop()
        model = self._get_model()
        embeddings = await loop.run_in_executor(
            None,
            lambda: model.encode(texts, normalize_embeddings=True).tolist(),
        )

        latency_ms = int((time.monotonic() - start) * 1000)

        logger.info(
            "embeddings_generated",
            model=self.model_name,
            count=len(texts),
            latency_ms=latency_ms,
        )

        return EmbeddingResponse(
            embeddings=embeddings,
            model=self.model_name,
            total_tokens=sum(len(t.split()) for t in texts),  # Approximate
            latency_ms=latency_ms,
        )

    def get_dimension(self) -> int:
        """Return the embedding vector dimension."""
        return self._dimension


# ── Factory ──────────────────────────────────────────────────────────────────

_embedder_instance: SentenceTransformerEmbedder | None = None


def get_embedding_provider() -> SentenceTransformerEmbedder:
    """Get or create the singleton embedding provider."""
    global _embedder_instance
    if _embedder_instance is None:
        _embedder_instance = SentenceTransformerEmbedder()
    return _embedder_instance
