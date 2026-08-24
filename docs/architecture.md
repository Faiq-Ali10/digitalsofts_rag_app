# Architecture Overview

## System Architecture

```
                    ┌─────────────────────┐
                    │    Next.js Client   │
                    │   React + Tailwind  │
                    └──────────┬──────────┘
                               │ HTTP/SSE
                               ▼
                    ┌─────────────────────┐
                    │    FastAPI Gateway   │
                    │  JWT Auth / CORS /   │
                    │  Rate Limit / Logs   │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  Agent Orchestrator  │
                    │    (LangGraph)       │
                    │                     │
                    │  classify_intent    │
                    │  retrieve_knowledge │
                    │  evaluate_retrieval │
                    │  rewrite_query      │
                    │  generate_answer    │
                    │  validate_action    │
                    │  execute_action     │
                    │  verify_response    │
                    └───────┬───────┬─────┘
                            │       │
             ┌──────────────┘       └───────────────┐
             ▼                                      ▼
      ┌─────────────┐                       ┌──────────────┐
      │ RAG Pipeline │                      │ Tool System  │
      │              │                      │              │
      │ Dense Search │                      │ Product Search│
      │ Sparse (FTS) │                      │ Demo Request │
      │ RRF Fusion   │                      │ Knowledge    │
      │ FlashRank    │                      │ Comparison   │
      └──────┬───────┘                      └──────┬───────┘
             │                                     │
       ┌─────▼──────┐                     ┌────────▼────────┐
       │ PostgreSQL  │◄────────────────────│  Tool Safety    │
       │ + pgvector  │                     │  Allowlist/RBAC │
       └──────┬──────┘                     │  Timeout/Audit  │
              │                            └─────────────────┘
       ┌──────▼──────────┐
       │ Arq Worker      │
       │ (Redis Queue)   │
       │                 │
       │ Parse → Chunk → │
       │ Embed → Index   │
       └─────────────────┘

        ┌─────────────────────┐
        │   LLM Abstraction   │
        │   (LiteLLM)         │
        │                     │
        │ Gemini (primary)    │
        │ Groq (fallback)     │
        │ Circuit Breaker     │
        │ Retry + Backoff     │
        └─────────────────────┘

        ┌─────────────────────┐
        │   Observability     │
        │                     │
        │ Structured Logging  │
        │ Prometheus Metrics  │
        │ Langfuse Tracing    │
        │ Audit Logs          │
        └─────────────────────┘
```

## Data Flow: Chat Request

1. User sends message via Next.js → `POST /api/v1/chat`
2. FastAPI validates JWT, extracts user, assigns request ID
3. Conversation is loaded/created, user message saved to DB
4. **Memory Injection**: Message history loaded for context. If history exceeds the threshold (15 messages), a background task summarizes older messages, which is then dynamically injected into the system prompt.
5. **Agent orchestrator** runs:
   a. **classify_intent** — Pattern + LLM classification
   b. Route to knowledge/action/unsupported
   c. **retrieve_knowledge** — Hybrid search (dense + sparse + RRF + rerank)
   d. **evaluate_retrieval** — Score quality, retry if needed
   e. **generate_answer** — RAG with citations using retrieved context
   f. **validate_action** — Checks if the action requires confirmation. If YES, the graph pauses and returns a `PENDING_CONFIRMATION` status.
   g. **verify_response** — Check for leakage, validate citations
6. Assistant response saved to DB with citations and metadata
7. Response returned with citations, confidence, and diagnostics

## Data Flow: Tool Confirmation

1. If the previous chat request returned `PENDING_CONFIRMATION`, the client prompts the user.
2. User approves via Next.js → `POST /api/v1/chat/tool/confirm`
3. The API re-hydrates the exact `AgentState` using the conversation memory.
4. The graph resumes directly at **execute_action** using the approved arguments.
5. The LLM generates a final response based on the tool's execution result.

## Data Flow: Document Ingestion

1. Admin uploads file via `POST /api/v1/documents`
2. File saved to disk, document record created (status: pending)
3. Job queued in Redis via Arq
4. HTTP 202 returned immediately
5. **Worker** picks up job:
   a. Parse file (PDF/MD/HTML/TXT)
   b. Check content hash for duplicates
   c. Chunk with recursive splitter (1000 chars, 200 overlap)
   d. Generate embeddings via sentence-transformers
   e. Store chunks + vectors in PostgreSQL
   f. Update document status (completed/failed)

## Key Design Principles

1. **Provider agnostic**: All LLM interactions go through `LLMProvider` interface
2. **Explicit control**: No autonomous agent loops. Max 3 iterations.
3. **Defense in depth**: Multiple security layers, not single point
4. **Fail gracefully**: Circuit breakers, timeouts, fallback responses
5. **Observable**: Every request has a trace with latency, tokens, and errors
6. **Typed state**: AgentState dataclass prevents uncontrolled mutations
