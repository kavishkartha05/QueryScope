FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Run as an unprivileged user with no home directory and no shell.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin demo

WORKDIR /srv

# Dependencies first so this layer is cached until requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

USER 10001
EXPOSE 8080

# Container-level liveness check using only the standard library.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2).status == 200 else 1)"

# --limit-concurrency makes uvicorn itself answer 503 beyond 100 open connections,
# on top of the app's own in-flight cap. Caps can be changed with DEMO_MAX_* env vars.
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080", \
     "--limit-concurrency", "100", "--timeout-keep-alive", "5", "--no-server-header"]
