# QueryScope Backend

FastAPI backend for the QueryScope developer observability tool.

## Setup

```bash
# Install dependencies
poetry install

# Copy and configure environment
cp .env.example .env

# Run database migrations
alembic upgrade head

# Start development server
uvicorn app.main:app --reload
```

## Structure

```
app/
├── api/        # Route handlers
├── core/       # config.py, db.py
├── models/     # SQLAlchemy ORM models
├── schemas/    # Pydantic request/response models
├── services/   # Business logic
└── main.py     # App factory
```

## Guardrails

The hosted demo limits what a run can do. All limits are settings (see
`.env.example`):

- **SSRF**: targets must be http(s) and must not be, or resolve to, loopback,
  private, link-local (including 169.254.169.254), CGNAT, multicast or reserved
  addresses, or their IPv6 equivalents. The name is resolved before each run and
  the connections are pinned to the validated addresses, so DNS cannot change
  the destination afterwards. Redirects are not followed.
- **Demo target URL**: `DEMO_TARGET_URL` is the full URL of the demo target (its host must also be in `ALLOWED_TARGET_HOSTS`); `GET /config` offers it in the UI target picker.
- **Allowlist**: `ALLOWED_TARGET_HOSTS`, exact hostnames, on by default when auth
  is enabled. The demo target service in `../demo-target` goes on this list.
- **Caps**: 500 requests, concurrency 20, 10 s per request, 60 s per run.
- **Quotas** (auth enabled): 2 runs at once overall, 1 per access code, and a daily
  request budget per code and overall; exceeding one returns 429.
- **Reaper**: runs stuck pending/running past the wall-clock limit plus a grace
  period are marked failed at startup and every minute.
- **LLM benchmark**: `POST /benchmark/llm` returns 404 unless `LLM_BENCHMARK_ENABLED`.
- **/health** returns 503 when the database cannot be reached.
