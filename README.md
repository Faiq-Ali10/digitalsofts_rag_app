# Digitalsofts Enterprise AI Knowledge & Action Assistant

A production-grade AI platform for answering enterprise questions from documentation, executing controlled actions through tools, and providing observable, authenticated, and evaluated AI interactions.

## Architecture

```
Client → FastAPI (Auth/Validation) → LangGraph Agent → RAG/Tools → PostgreSQL+pgvector
                                         ↓
                                    LiteLLM (Gemini/Groq)
```

**Key components:**
- **LangGraph Agent**: Explicit state machine with intent classification, retrieval, generation, and tool execution
- **Hybrid Retrieval**: Dense (pgvector) + Sparse (FTS) + RRF + FlashRank reranking
- **4 Tools**: Product search, demo requests, knowledge search, product comparison — with safety layer
- **LLM Abstraction**: Gemini primary, Groq fallback, circuit breaker + exponential backoff
- **Local Embeddings**: sentence-transformers (all-MiniLM-L6-v2) — no API dependency

See [docs/architecture.md](docs/architecture.md) for detailed architecture documentation.

## Quick Start

### Prerequisites
- Docker and Docker Compose
- Gemini API key (required)
- Groq API key (optional, for fallback)

### Setup

```bash
# 1. Clone the repository
git clone <repo-url> && cd digitalsofts

# 2. Create .env from template
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY

# 3. Start all services
docker-compose up -d

# 4. Run database migrations
docker-compose exec backend alembic upgrade head

# 5. Seed initial data (products)
docker-compose exec backend python -m app.db.seed

# 6. Open the application
# API: http://localhost:8000/docs
# Frontend: http://localhost:3000
```

### Local Development (Frontend)

If you prefer to run the frontend locally outside of Docker:
```bash
cd frontend
npm install
npm run dev
```

### Without Docker (development)

```bash
# 1. Start PostgreSQL and Redis (local or Docker)
docker-compose up -d postgres redis

# 2. Set up Python environment
cd backend
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"

# 3. Run migrations
alembic upgrade head

# 4. Start the API server
uvicorn app.main:app --reload --port 8000

# 5. Start the worker (separate terminal)
python -m arq app.ingestion.worker.WorkerSettings
```

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | Yes | — | Google Gemini API key |
| `GROQ_API_KEY` | No | — | Groq API key (fallback) |
| `DATABASE_URL` | No | postgresql+asyncpg://... | PostgreSQL connection URL |
| `REDIS_URL` | No | redis://localhost:6379/0 | Redis connection URL |
| `JWT_SECRET_KEY` | Yes | — | Secret for JWT signing |
| `SECRET_KEY` | Yes | — | Application secret |
| `EMBEDDING_MODEL_NAME` | No | all-MiniLM-L6-v2 | Sentence-transformers model |

See [.env.example](.env.example) for all variables.

## API Endpoints

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/v1/auth/register` | — | Register new user |
| POST | `/api/v1/auth/login` | — | Login and get tokens |
| POST | `/api/v1/auth/refresh` | — | Refresh access token |
| GET | `/api/v1/auth/me` | User | Get current user profile |
| POST | `/api/v1/chat` | User | Send a chat message |
| GET | `/api/v1/conversations` | User | List conversations |
| GET | `/api/v1/conversations/{id}` | User | Get conversation messages |
| POST | `/api/v1/feedback` | User | Submit response feedback |
| POST | `/api/v1/documents` | Admin | Upload document |
| POST | `/api/v1/documents/{id}/ingest` | Admin | Re-trigger ingestion |
| GET | `/api/v1/documents` | User | List documents |
| DELETE | `/api/v1/documents/{id}` | Admin | Delete document |
| GET | `/api/v1/health` | — | Liveness probe |
| GET | `/api/v1/ready` | — | Readiness probe |
| GET | `/api/v1/metrics` | — | Prometheus metrics |

Full API documentation available at `http://localhost:8000/docs` (Swagger UI).

## Document Ingestion

```bash
# Upload a document (requires admin token)
curl -X POST http://localhost:8000/api/v1/documents \
  -H "Authorization: Bearer <admin-token>" \
  -F "file=@data/raw/products/poultry-erp.md" \
  -F "title=Poultry ERP Documentation" \
  -F "product=poultry-erp"
```

Supported formats: PDF, Markdown, HTML, plain text.

Documents are ingested asynchronously via the Arq worker.

## Running Tests

All automated tests (Integration, API, RAG, and Security) are executed within the backend Docker container to ensure environment consistency and that all dependencies (like PostgreSQL and Redis) are correctly wired up.

```bash
# All tests
docker-compose exec backend pytest tests/ -v

# Unit tests only
docker-compose exec backend pytest tests/unit/ -v

# Integration tests only
docker-compose exec backend pytest tests/integration/ -v

# Security tests only
docker-compose exec backend pytest tests/security/ -v
```

## Running Evaluation

```bash
cd backend
python -c "
import asyncio
from app.evaluation.evaluator import run_evaluation
results, summary = asyncio.run(run_evaluation())
print(f'Total: {summary.total_questions}')
print(f'Relevance: {summary.answer_relevance_rate:.1%}')
print(f'Hallucination: {summary.hallucination_rate:.1%}')
print(f'Injection blocked: {summary.injection_block_rate:.1%}')
"
```

Results saved to `evaluation/results/`.

## Technology Stack

| Component | Technology | Rationale |
|---|---|---|
| Backend | FastAPI | Async, Pydantic, DI, OpenAPI |
| Agent | LangGraph | Explicit state machine |
| LLM | LiteLLM (Gemini/Groq) | Provider abstraction |
| Embeddings | sentence-transformers | Local, no API cost |
| Reranking | FlashRank | Local cross-encoder |
| Database | PostgreSQL + pgvector | Single DB for relational + vector |
| Queue | Arq (Redis) | Async-native task queue |
| Auth | JWT + bcrypt | Stateless, RBAC |
| Logging | structlog | Structured JSON logging |
| Metrics | Prometheus | Standard observability |
| Testing | pytest | Async-first |
| CI/CD | GitHub Actions | Lint, test, build, security |

## Documentation

- [Architecture](docs/architecture.md) — System design and data flows
- [Security](docs/security.md) — Threat model, defenses, and limitations
- [Evaluation](docs/evaluation.md) — AI evaluation methodology and metrics
- [Decisions](docs/decisions.md) — Architecture Decision Records (ADRs)

## Production Readiness

### Reliability
- **LLM unavailable**: Circuit breaker pattern with automatic fallback to Groq. After 5 consecutive failures, requests fail-fast for 60 seconds.
- **Retrieval failure**: Returns "I don't have enough information" with error logged.

### Cost Control
- Local embeddings (zero API cost)
- Gemini Flash for chat (low token cost)
- Token tracking per request
- Max token limits on all LLM calls

### Scaling
| Scale | Changes Needed |
|---|---|
| 100 users | Current architecture sufficient |
| 1,000 users | pgbouncer, Redis caching, horizontal API scaling |
| 100,000 users | Qdrant, Kubernetes, dedicated embedding service |

### Observability
- Structured JSON logs with request ID, user ID, latency
- Prometheus metrics (requests, latency, tokens, tool calls)
- Langfuse tracing (optional, self-hosted)
- Audit logs for all tool executions

## If Digitalsofts Hired Me (Next 90 Days)

### Month 1: Harden
- Add column-level encryption for sensitive data
- Implement proper rate limiting with Redis sliding window
- Set up Langfuse self-hosted for production tracing
- Add comprehensive integration tests with real LLM calls
- Implement proper conversation summarization

### Month 2: Scale
- Migrate to Qdrant for vector search at scale
- Add semantic caching (avoid redundant LLM calls)
- Implement SSE streaming for real-time responses
- Build admin dashboard for document and evaluation management
- Add multi-language support

### Month 3: Optimize
- Run Ragas evaluation on production traffic
- Implement A/B testing for prompt variants
- Add fine-tuned reranker on domain data
- Set up alerting on quality metrics (hallucination rate, latency)
- Implement proper data retention and privacy controls

## Known Limitations

1. **No SSE streaming yet**: Responses are returned as complete JSON. Streaming architecture is stubbed but not fully implemented.
2. **Single-turn tool confirmation**: Tool confirmation works for simple cases but doesn't support multi-step confirmation workflows.
3. **Evaluation is rule-based**: Uses keyword matching rather than LLM-as-judge. Adequate for initial assessment but should be augmented with Ragas/DeepEval for production.
4. **No multi-tenancy**: All users share the same knowledge base. Multi-tenant isolation would require per-tenant vector spaces.
5. **Frontend is minimal**: Focused on engineering quality per assignment requirements, not UI polish.

## License

Proprietary — Digitalsofts Technical Assessment

## Author

Faiq Ali — AI/ML Engineer Candidate
