# QueryScope

> Developer observability tool that runs load benchmarks against REST and LLM-backed API endpoints, stores results, and lets engineers query degradation patterns in natural language via a RAG pipeline.

**The gap QueryScope fills:** existing load testers (k6, JMeter) produce static reports with no AI layer. LLM observability tools (LangSmith, Langfuse) monitor AI apps but don't run load tests. QueryScope sits in the middle — self-hostable, open-source, and AI-powered.

---

## Video Demo
https://www.loom.com/share/aa0458b3b73849f4b8c731217b443b6f

---

## Demo

Point QueryScope at any endpoint, run a configurable benchmark, and ask questions in natural language:

> "Why did p99 spike compared to my last run?"
> "Which endpoint had the worst tail latency?"
> "Compare the Palantir run against the Amazon run"

You can also trigger benchmarks directly from Claude Desktop or Cursor via the MCP server.

---

## Architecture
```
┌──────────────────────────────────────────────────────────┐
│                     React Dashboard                      │
│         Benchmark form · Runs table · Latency chart      │
│              Natural language diagnose panel             │
└───────────────────────┬──────────────────────────────────┘
                        │ HTTP
┌───────────────────────▼──────────────────────────────────┐
│                   FastAPI Backend                        │
│                                                          │
│  POST /benchmark     → Benchmark runner (httpx + asyncio)│
│  GET  /runs          → PostgreSQL via async SQLAlchemy   │
│  POST /diagnose      → LangChain RCA chain               │
│  POST /benchmark/llm → LLM endpoint benchmarking (TTFT)  │
└──────┬──────────────────────┬────────────────────────────┘
       │                      │
┌──────▼──────┐    ┌──────────▼────────────────────────────┐
│  PostgreSQL │    │           AI Layer                    │
│             │    │                                       │
│  runs       │    │  LlamaIndex → OpenAI Embeddings       │
│  metrics    │    │           ↓                           │
│             │    │  Azure AI Search (vector index)       │
└─────────────┘    │           ↓                           │
                   │  LangChain LCEL RCA chain             │
                   │  (GPT-4o-mini + retrieval context)    │
                   └───────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│              Node.js MCP Server                         │
│                                                         │
│  run_benchmark  →  POST /benchmark                      │
│  query_runs     →  GET  /runs                           │
│                                                         │
│  Works with Claude Desktop, Cursor, any MCP client      │
└─────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React, TypeScript, Vite, Recharts |
| Backend | FastAPI, async SQLAlchemy, Alembic, asyncpg |
| AI orchestration | LangChain (LCEL RCA chain), LlamaIndex (indexing + retrieval) |
| LLM | OpenAI GPT-4o-mini (diagnosis), text-embedding-3-small (embeddings) |
| Vector store | Azure AI Search |
| Databases | PostgreSQL (primary), MySQL via aiomysql (adapter swap demo) |
| MCP server | Node.js, @modelcontextprotocol/sdk |
| Infra | Docker Compose (local), Kubernetes + HPA (production), AWS EC2 |

---

## How It Works

### Load benchmarking
QueryScope fires configurable concurrent HTTP requests at any REST endpoint using `httpx.AsyncClient` with an `asyncio.Semaphore` for concurrency control. Each request's latency is recorded in milliseconds. After all requests complete, `numpy.percentile` computes p50/p95/p99. Results are stored in PostgreSQL with raw latency arrays for later analysis.

### LLM endpoint benchmarking
A dedicated mode for AI APIs measures time-to-first-token (TTFT) and chunks-per-second by consuming the SSE stream incrementally. Useful for comparing OpenAI vs Gemini vs Claude response characteristics under load.

### RAG pipeline
Every completed benchmark run is indexed into Azure AI Search:
1. A plain-text summary is generated: `"Benchmark run {id} against {url} ({method}) with {n} requests. p50={p50}ms p95={p95}ms p99={p99}ms throughput={tps}req/s error_rate={err}"`
2. OpenAI `text-embedding-3-small` embeds the summary into a 1536-dimensional vector
3. LlamaIndex upserts the document + vector into Azure AI Search

When you ask a question via `/diagnose`:
1. The question is embedded using the same model
2. Azure AI Search performs a vector similarity search returning the top 5 semantically relevant runs
3. The 5 most recent runs are also fetched directly from PostgreSQL (ensures recency)
4. Both context sources are injected into a LangChain LCEL prompt
5. GPT-4o-mini generates a grounded root cause diagnosis

### MCP server
The Node.js MCP server exposes two tools over stdio:
- `run_benchmark(target_url, method, num_requests, concurrency)` — triggers a benchmark and returns the run_id
- `query_runs(limit)` — returns a formatted summary of recent benchmark runs with latency metrics

Connect it to Claude Desktop and you can say "benchmark httpbin with 50 requests at concurrency 10" and Claude will call the tool, run the benchmark, and analyze the results autonomously.

---

## Quick Start

### Docker Compose (recommended)
```bash
git clone https://github.com/kavishkartha/QueryScope.git
cd QueryScope

# Configure environment
cp backend/.env.example backend/.env
# Fill in: OPENAI_API_KEY, AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_KEY

# Start everything
docker compose up --build
```

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API docs: http://localhost:8000/docs

### Local development
```bash
# Backend
cd backend
poetry install
poetry run alembic upgrade head
poetry run uvicorn app.main:app --reload

# Frontend (separate terminal)
cd frontend
npm install
npm run dev

# MCP server (separate terminal)
cd mcp-server
npm install
npm start
```

### Azure AI Search setup
```bash
cd backend
poetry run python scripts/create_azure_index.py
```

---

## Kubernetes Deployment
```bash
# Start minikube
minikube start
minikube addons enable metrics-server
minikube tunnel  # keep open in a separate terminal

# Build images into minikube
eval $(minikube docker-env)
docker build -t queryscope-backend:latest ./backend
docker build -t queryscope-frontend:latest ./frontend

# Create namespace and secrets
kubectl apply -f k8s/namespace.yaml
kubectl create secret generic queryscope-secrets \
  --namespace queryscope \
  --from-literal=OPENAI_API_KEY=<key> \
  --from-literal=AZURE_SEARCH_ENDPOINT=<endpoint> \
  --from-literal=AZURE_SEARCH_KEY=<key> \
  --from-literal=AZURE_SEARCH_INDEX=benchmark-runs

# Deploy
kubectl apply -f k8s/

# Access
minikube service frontend -n queryscope
minikube service backend -n queryscope
```

The HPA scales backend pods from 2 to 6 replicas when CPU exceeds 70%.

---

## Claude Desktop Integration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "queryscope": {
      "command": "/path/to/node",
      "args": [
        "/path/to/QueryScope/mcp-server/node_modules/.bin/ts-node",
        "/path/to/QueryScope/mcp-server/src/index.ts"
      ]
    }
  }
}
```

Then ask Claude: *"Use queryscope to benchmark https://api.example.com/endpoint with 20 requests"*

---

## MySQL Adapter

QueryScope defaults to PostgreSQL but supports MySQL via a config swap:
```bash
# In backend/.env
DATABASE_URL=mysql+aiomysql://user:password@host:3306/queryscope

# Run migrations
poetry run alembic upgrade head
```

The `metrics.latencies` column uses `sa.JSON` instead of PostgreSQL's native `ARRAY` type, making it compatible with both databases. See `backend/docs/mysql-adapter.md` for details.

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/benchmark` | Start a REST load benchmark |
| `POST` | `/benchmark/llm` | Start an LLM endpoint benchmark (TTFT) |
| `GET` | `/benchmark/runs` | List all runs with metrics |
| `GET` | `/benchmark/runs/{id}` | Get a specific run |
| `GET` | `/benchmark/runs/{id}/metrics` | Get raw latencies + aggregates |
| `POST` | `/benchmark/diagnose` | Natural language root cause analysis |
| `GET` | `/health` | Health check |

Full interactive docs at `http://localhost:8000/docs`

---
