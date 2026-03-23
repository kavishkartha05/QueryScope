FROM python:3.11-slim

# System deps needed by asyncpg (C extension) and Poetry itself.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    libpq-dev \
 && rm -rf /var/lib/apt/lists/*

# Install Poetry — pinned so CI builds are reproducible.
RUN curl -sSL https://install.python-poetry.org | python3 - && \
    ln -s /root/.local/bin/poetry /usr/local/bin/poetry

WORKDIR /app

# Copy dependency manifests first so Docker can cache the install layer.
# Re-installing only happens when pyproject.toml or poetry.lock changes.
COPY pyproject.toml poetry.lock ./

# --no-root skips installing the package itself (we COPY the source below).
# --no-interaction / --no-ansi keep output clean in CI.
RUN poetry install --no-root --no-interaction --no-ansi

# Copy the rest of the source after deps so source changes don't bust the cache.
COPY . .

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
