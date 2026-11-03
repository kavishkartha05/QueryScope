"""
QueryScope demo target: a tiny HTTP service that benchmarks can safely hit.

It is deliberately NOT a route on the QueryScope backend. The backend refuses to
call loopback and private addresses (SSRF protection), so a demo target inside
the backend process would be unreachable by design. Deploy this as its own
service with a public hostname and put that hostname on ALLOWED_TARGET_HOSTS.

  GET|POST /work?latency_ms=120&jitter_ms=40&error_rate=0.05&error_status=503
  GET      /health

  latency_ms    fixed delay before answering            0 .. DEMO_MAX_LATENCY_MS
  jitter_ms     extra random delay, uniform 0..jitter   latency_ms + jitter_ms <= max
  error_rate    probability of an error response        0 .. 1
  error_status  status used for errors                  500, 502, 503 or 504

Its own caps, so it cannot be turned into a slow-response or load amplifier:
  - delay is capped (default 2000 ms) and out-of-range values are rejected, not clamped
  - at most DEMO_MAX_INFLIGHT requests are handled at once (default 50); more get
    an immediate 503, so held-open connections cannot pile up
  - responses are a fixed tiny JSON body; nothing from the request is echoed
  - request bodies are never read, and a declared body over 10 KB gets 413
  - only GET and POST (and /health); no docs or OpenAPI endpoints
The Dockerfile also sets uvicorn's own connection limit.
"""
import asyncio
import os
import random
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse


def _env_number(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass
class Limits:
    max_latency_ms: float
    max_inflight: int
    max_body_bytes: int


# Read once at import. Tests change the attributes of this object.
LIMITS = Limits(
    max_latency_ms=_env_number("DEMO_MAX_LATENCY_MS", 2000.0),
    max_inflight=int(_env_number("DEMO_MAX_INFLIGHT", 50)),
    max_body_bytes=10_240,
)

ERROR_STATUSES = (500, 502, 503, 504)

# Single event loop thread: the counter needs no lock because there is no
# await between the check and the increment.
_state = {"inflight": 0}
_rng = random.Random()

app = FastAPI(
    title="QueryScope demo target",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def _number_param(request: Request, name: str, default: float) -> float:
    raw = request.query_params.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{name} must be a number")
    if value != value or value in (float("inf"), float("-inf")):
        raise HTTPException(status_code=422, detail=f"{name} must be a finite number")
    return value


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.api_route("/work", methods=["GET", "POST"])
async def work(request: Request) -> JSONResponse:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > LIMITS.max_body_bytes:
        return JSONResponse({"detail": "request body too large"}, status_code=413)

    latency_ms = _number_param(request, "latency_ms", 0.0)
    jitter_ms = _number_param(request, "jitter_ms", 0.0)
    error_rate = _number_param(request, "error_rate", 0.0)
    status_raw = _number_param(request, "error_status", 500.0)

    if latency_ms < 0 or jitter_ms < 0:
        raise HTTPException(status_code=422, detail="latency_ms and jitter_ms must be 0 or more")
    if latency_ms + jitter_ms > LIMITS.max_latency_ms:
        raise HTTPException(
            status_code=422,
            detail=f"latency_ms + jitter_ms must be at most {LIMITS.max_latency_ms:g}",
        )
    if error_rate < 0 or error_rate > 1:
        raise HTTPException(status_code=422, detail="error_rate must be between 0 and 1")
    if status_raw != int(status_raw) or int(status_raw) not in ERROR_STATUSES:
        raise HTTPException(status_code=422, detail="error_status must be one of 500, 502, 503, 504")
    error_status = int(status_raw)

    if _state["inflight"] >= LIMITS.max_inflight:
        return JSONResponse(
            {"detail": "demo target is at capacity"}, status_code=503, headers={"Retry-After": "1"}
        )
    _state["inflight"] += 1
    try:
        delay_ms = latency_ms + (_rng.random() * jitter_ms if jitter_ms > 0 else 0.0)
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000.0)
        if error_rate > 0 and _rng.random() < error_rate:
            return JSONResponse({"ok": False}, status_code=error_status)
        return JSONResponse({"ok": True, "delay_ms": round(delay_ms, 1)})
    finally:
        _state["inflight"] -= 1
