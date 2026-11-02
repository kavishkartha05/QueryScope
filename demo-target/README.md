# QueryScope demo target

A small standalone service that QueryScope benchmarks can safely call. It has
configurable artificial latency and error rate, and its own limits so it cannot be
abused.

It is a separate service on purpose. The QueryScope backend refuses loopback and
private addresses (SSRF protection), so a demo route inside the backend would be
unreachable. Deploy this with a public hostname instead.

## Endpoints

| Path | Methods | Purpose |
|---|---|---|
| `/work` | GET, POST | The benchmark target (query parameters below) |
| `/health` | GET | Liveness |

`/work` parameters, all optional:

| Parameter | Default | Meaning |
|---|---|---|
| `latency_ms` | 0 | Fixed delay before answering |
| `jitter_ms` | 0 | Extra random delay, uniform between 0 and this value |
| `error_rate` | 0 | Probability (0 to 1) of answering with an error status |
| `error_status` | 500 | Status for errors: 500, 502, 503 or 504 |

Example: `/work?latency_ms=120&jitter_ms=40&error_rate=0.05&error_status=503`

## Limits

| Limit | Default | Setting |
|---|---|---|
| `latency_ms + jitter_ms` | 2000 ms (larger values get 422, not clamped) | `DEMO_MAX_LATENCY_MS` |
| Requests handled at once | 50 (more get an immediate 503) | `DEMO_MAX_INFLIGHT` |
| Declared request body | 10 KB (larger gets 413); bodies are never read | fixed |
| Open connections | 100 (uvicorn answers 503 beyond it) | `--limit-concurrency` in the Dockerfile |

Responses are a fixed tiny JSON body and nothing from the request is echoed. There
are no docs or OpenAPI endpoints. For a stronger guarantee against raw request
floods, also put platform rate limiting in front of it.

## Run it

```
pip install -r requirements.txt
uvicorn server:app --port 8080
```

or

```
docker build -t queryscope-demo-target .
docker run --rm -p 8080:8080 queryscope-demo-target
```

## Use it from QueryScope

1. Deploy it somewhere with a public hostname, for example `demo.example.com`.
2. Add that exact hostname to the backend's allowlist (exact match, no wildcards):
   `ALLOWED_TARGET_HOSTS=httpbin.org,demo.example.com`
3. Benchmark `https://demo.example.com/work?latency_ms=100&error_rate=0.02`.

The backend's SSRF checks still apply to it: the hostname must resolve to a public
address. For local development against a demo target on localhost, run the backend
with `BLOCK_PRIVATE_TARGETS=false` (and `AUTH_ENABLED=false`, which also turns the
allowlist off).

## Tests

```
pip install -r requirements.txt pytest pytest-asyncio httpx
pytest
```
