# QueryScope

Developer observability tool that runs load benchmarks against REST and LLM-backed
API endpoints, stores results in PostgreSQL, and lets engineers query degradation
patterns in natural language via a RAG pipeline.

## Stack

- Backend: FastAPI (Python 3.11+), async SQLAlchemy, Alembic
- Frontend: React + TypeScript, Recharts
- AI: LlamaIndex, LangChain, Azure AI Search, OpenAI/Gemini/Claude
- MCP server: Node.js (separate package)
- DBs: PostgreSQL (primary), MySQL (adapter swap demo)
- Infra: Docker Compose (local), Kubernetes + HPA (prod), AWS EC2

## Project structure

queryscope/
├── backend/          # FastAPI app
│   ├── app/
│   │   ├── api/      # route handlers
│   │   ├── core/     # config, db, settings
│   │   ├── models/   # SQLAlchemy ORM models
│   │   ├── schemas/  # Pydantic request/response models
│   │   ├── services/ # business logic (runner, indexer, rca)
│   │   └── main.py
│   ├── alembic/
│   └── tests/
├── frontend/         # React + TypeScript
├── mcp-server/       # Node.js MCP server
├── k8s/              # Kubernetes manifests
├── docs/             # Architecture docs, prompt sequences
└── docker-compose.yml

## Dev commands

# Backend
cd backend && uvicorn app.main:app --reload   # start API
cd backend && alembic upgrade head            # run migrations
cd backend && pytest                          # run tests

# Frontend
cd frontend && npm run dev

## Working style

- Generate complete, working implementations — don't hold back
- Add brief inline comments on non-obvious decisions (e.g. why async, why a semaphore)
- Prefer the simplest correct implementation over the cleverest one

## Key decisions

- Use httpx (async) for the benchmark HTTP engine — not requests
- All DB access via async SQLAlchemy (asyncpg driver for Postgres)
- Pydantic v2 for all schemas
- Metrics stored per-request during a run, aggregated on read
- p50/p95/p99 computed with numpy percentile over raw latency arrays
- Azure AI Search is the ONLY vector store — do not add alternatives
- LangChain LCEL for the RCA chain — not legacy chain syntax
- MCP server is a separate Node.js package — do not mix with FastAPI

## Do not

- Do not use synchronous SQLAlchemy — always async
- Do not store aggregated metrics only — keep raw per-request latencies
- Do not add Redis or a task queue in Week 1 — keep it simple