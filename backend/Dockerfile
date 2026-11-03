# syntax=docker/dockerfile:1

# ---- builder: Poetry and compilers live here only -------------------------
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Matches the version that wrote poetry.lock (lock-version 2.1).
    POETRY_VERSION=2.5.1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_NO_INTERACTION=1

# build-essential covers any dependency that has no prebuilt wheel.
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/* \
 && pip install "poetry==${POETRY_VERSION}"

WORKDIR /app

# Manifests first so the dependency layer is cached until they change.
COPY pyproject.toml poetry.lock ./

# --only main: no pytest/httpx/aiosqlite in the image. --no-root: the source is
# copied below and run from /app.
RUN poetry install --only main --no-root --no-ansi

# ---- runtime: no Poetry, no compilers, non-root ---------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/app/.venv/bin:$PATH" \
    # Hosted default: the image never migrates on start. Migrations run as a
    # separate one-off job (see docs/deploy.md). docker-compose sets this to true.
    RUN_MIGRATIONS=false

RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY . .
RUN chmod 0755 /app/entrypoint.sh

USER 10001
EXPOSE 8000

# Standard-library probe so no curl is needed in the image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["/app/entrypoint.sh"]
