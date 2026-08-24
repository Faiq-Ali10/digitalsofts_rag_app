"""Hybrid retrieval system with Reciprocal Rank Fusion and reranking.

Architecture:
  Query → Dense (pgvector) + Sparse (PostgreSQL FTS)
        → Reciprocal Rank Fusion
        → Metadata Filtering
        → Chunk Deduplication
        → FlashRank Reranking
        → Similarity Threshold
        → Context Construction

Design rationale:
- Hybrid retrieval captures both semantic (dense) and lexical (sparse)
  matches — important for enterprise docs with technical terminology.
- RRF merges results without requiring score normalization across methods.
- FlashRank cross-encoder reranking significantly improves precision
  at low cost (runs locally, ~50ms for 20 candidates).
- Metadata filtering enables scoped search (e.g., "only poultry ERP docs").
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.llm.embeddings import get_embedding_provider

settings = get_settings()
logger = structlog.get_logger(__name__)


@dataclass
class RetrievedChunk:
    """A retrieved document chunk with relevance metadata."""

    chunk_id: str
    document_id: str
    content: str
    score: float
    metadata: dict = field(default_factory=dict)
    retrieval_method: str = "hybrid"


@dataclass
class RetrievalResult:
    """Complete retrieval result with diagnostics."""

    chunks: list[RetrievedChunk]
    query: str
    latency_ms: int = 0
    dense_count: int = 0
    sparse_count: int = 0
    reranked: bool = False


async def hybrid_retrieve(
    query: str,
    db: AsyncSession,
    *,
    top_k: int | None = None,
    rerank_top_k: int | None = None,
    similarity_threshold: float | None = None,
    metadata_filters: dict | None = None,
) -> RetrievalResult:
    """Execute hybrid retrieval: dense + sparse + RRF + reranking.

    Args:
        query: User's search query.
        db: Async database session.
        top_k: Number of candidates to fetch from each method.
        rerank_top_k: Number of final results after reranking.
        similarity_threshold: Minimum score to include.
        metadata_filters: Optional filters (e.g., {"product": "poultry-erp"}).

    Returns:
        RetrievalResult with ranked chunks and diagnostics.
    """
    start = time.monotonic()
    top_k = top_k or settings.rag_top_k
    rerank_top_k = rerank_top_k or settings.rag_rerank_top_k
    threshold = similarity_threshold if similarity_threshold is not None else settings.rag_similarity_threshold

    # 1. Dense retrieval (pgvector cosine similarity)
    dense_results = await _dense_search(query, db, top_k, metadata_filters)

    # 2. Sparse retrieval (PostgreSQL full-text search)
    sparse_results = await _sparse_search(query, db, top_k, metadata_filters)

    logger.info(
        "retrieval_raw_results",
        dense_count=len(dense_results),
        sparse_count=len(sparse_results),
    )

    # 3. Reciprocal Rank Fusion
    fused = _reciprocal_rank_fusion(dense_results, sparse_results, k=60)

    # 4. Chunk deduplication (keep highest-scored chunk per document)
    deduped = _deduplicate_by_document(fused)

    # 5. Reranking (FlashRank cross-encoder)
    if deduped:
        reranked = await _rerank(query, deduped, top_n=rerank_top_k)
        used_reranking = True
    else:
        reranked = deduped
        used_reranking = False

    # 6. Similarity threshold
    filtered = [c for c in reranked if c.score >= threshold]

    latency_ms = int((time.monotonic() - start) * 1000)

    logger.info(
        "retrieval_completed",
        query=query[:100],
        results=len(filtered),
        latency_ms=latency_ms,
        reranked=used_reranking,
    )

    return RetrievalResult(
        chunks=filtered,
        query=query,
        latency_ms=latency_ms,
        dense_count=len(dense_results),
        sparse_count=len(sparse_results),
        reranked=used_reranking,
    )


async def _dense_search(
    query: str,
    db: AsyncSession,
    top_k: int,
    metadata_filters: dict | None,
) -> list[RetrievedChunk]:
    """Vector similarity search using pgvector."""
    embedder = get_embedding_provider()
    response = await embedder.embed([query])
    query_embedding = response.embeddings[0]

    # Build parameterized query
    sql = """
        SELECT
            dc.id::text AS chunk_id,
            dc.document_id::text AS document_id,
            dc.content,
            dc.metadata,
            1 - (dc.embedding <=> CAST(:embedding AS vector)) AS similarity
        FROM document_chunks dc
        JOIN documents d ON dc.document_id = d.id
        WHERE d.status = 'completed'
    """
    params: dict = {"embedding": str(query_embedding)}

    if metadata_filters:
        if "product" in metadata_filters:
            sql += " AND d.product = :product"
            params["product"] = metadata_filters["product"]
        if "document_type" in metadata_filters:
            sql += " AND d.document_type = :doc_type"
            params["doc_type"] = metadata_filters["document_type"]

    sql += " ORDER BY dc.embedding <=> CAST(:embedding AS vector) LIMIT :limit"
    params["limit"] = top_k

    result = await db.execute(text(sql), params)
    rows = result.fetchall()

    return [
        RetrievedChunk(
            chunk_id=row.chunk_id,
            document_id=row.document_id,
            content=row.content,
            score=float(row.similarity),
            metadata=row.metadata or {},
            retrieval_method="dense",
        )
        for row in rows
    ]


async def _sparse_search(
    query: str,
    db: AsyncSession,
    top_k: int,
    metadata_filters: dict | None,
) -> list[RetrievedChunk]:
    """Full-text search using PostgreSQL ts_vector."""
    # Convert query to tsquery format
    sql = """
        SELECT
            dc.id::text AS chunk_id,
            dc.document_id::text AS document_id,
            dc.content,
            dc.metadata,
            ts_rank_cd(
                to_tsvector('english', dc.content),
                plainto_tsquery('english', :query)
            ) AS rank
        FROM document_chunks dc
        JOIN documents d ON dc.document_id = d.id
        WHERE d.status = 'completed'
          AND to_tsvector('english', dc.content) @@ plainto_tsquery('english', :query)
    """
    params: dict = {"query": query}

    if metadata_filters:
        if "product" in metadata_filters:
            sql += " AND d.product = :product"
            params["product"] = metadata_filters["product"]
        if "document_type" in metadata_filters:
            sql += " AND d.document_type = :doc_type"
            params["doc_type"] = metadata_filters["document_type"]

    sql += " ORDER BY rank DESC LIMIT :limit"
    params["limit"] = top_k

    result = await db.execute(text(sql), params)
    rows = result.fetchall()

    return [
        RetrievedChunk(
            chunk_id=row.chunk_id,
            document_id=row.document_id,
            content=row.content,
            score=float(row.rank),
            metadata=row.metadata or {},
            retrieval_method="sparse",
        )
        for row in rows
    ]


def _reciprocal_rank_fusion(
    *result_lists: list[RetrievedChunk],
    k: int = 60,
) -> list[RetrievedChunk]:
    """Merge multiple ranked lists using Reciprocal Rank Fusion.

    RRF score = sum(1 / (k + rank_i)) for each list where the item appears.
    The k parameter (default 60) controls rank sensitivity.
    """
    chunk_map: dict[str, RetrievedChunk] = {}
    rrf_scores: dict[str, float] = {}

    for result_list in result_lists:
        for rank, chunk in enumerate(result_list):
            key = chunk.chunk_id

            if key not in chunk_map:
                chunk_map[key] = chunk
                rrf_scores[key] = 0.0

            rrf_scores[key] += 1.0 / (k + rank + 1)

    # Sort by RRF score
    sorted_keys = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)

    results = []
    for key in sorted_keys:
        chunk = chunk_map[key]
        chunk.score = rrf_scores[key]
        chunk.retrieval_method = "hybrid_rrf"
        results.append(chunk)

    return results


def _deduplicate_by_document(
    chunks: list[RetrievedChunk],
    max_per_document: int = 3,
) -> list[RetrievedChunk]:
    """Keep at most N chunks per document to ensure diversity."""
    doc_counts: dict[str, int] = {}
    deduped = []

    for chunk in chunks:
        count = doc_counts.get(chunk.document_id, 0)
        if count < max_per_document:
            deduped.append(chunk)
            doc_counts[chunk.document_id] = count + 1

    return deduped


async def _rerank(
    query: str,
    chunks: list[RetrievedChunk],
    top_n: int = 5,
) -> list[RetrievedChunk]:
    """Rerank chunks using FlashRank cross-encoder.

    Cross-encoders are more accurate than bi-encoders (used in dense search)
    because they process query-document pairs jointly. However, they're too
    slow for first-stage retrieval, so we use them only on the top candidates.
    """
    import asyncio

    if not chunks:
        return []

    try:
        from flashrank import Ranker, RerankRequest

        loop = asyncio.get_event_loop()

        def _do_rerank():
            ranker = Ranker(model_name="ms-marco-MiniLM-L-12-v2", cache_dir="/tmp/flashrank")
            passages = [
                {"id": i, "text": c.content, "meta": {"chunk_id": c.chunk_id}}
                for i, c in enumerate(chunks)
            ]
            request = RerankRequest(query=query, passages=passages)
            results = ranker.rerank(request)
            return results

        results = await loop.run_in_executor(None, _do_rerank)

        # Map reranked scores back to chunks
        chunk_map = {c.chunk_id: c for c in chunks}
        reranked = []

        for result in results[:top_n]:
            chunk_id = result["meta"]["chunk_id"]
            if chunk_id in chunk_map:
                chunk = chunk_map[chunk_id]
                chunk.score = float(result["score"])
                chunk.retrieval_method = "reranked"
                reranked.append(chunk)

        return reranked

    except Exception as e:
        logger.warning("reranking_failed", error=str(e))
        # Fall back to original ordering
        return chunks[:top_n]
