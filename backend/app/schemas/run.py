import uuid
from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl

from app.models.run import RunStatus


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class BenchmarkRequest(BaseModel):
    target_url: HttpUrl
    method: str = Field(default="GET", max_length=10, pattern=r"^[A-Z]+$")
    num_requests: int = Field(ge=1, le=10_000)
    concurrency: int = Field(ge=1, le=500)
    headers: dict[str, str] | None = None
    body: dict | None = None


class LLMBenchmarkRequest(BaseModel):
    endpoint_url: HttpUrl
    # api_key is kept out of logs; callers must pass it per-request.
    api_key: str
    model: str
    prompt: str
    num_requests: int = Field(default=10, ge=1, le=1_000)
    concurrency: int = Field(default=3, ge=1, le=50)


class DiagnoseRequest(BaseModel):
    question: str


class DiagnoseResponse(BaseModel):
    diagnosis: str


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class MetricsSummary(BaseModel):
    """Aggregates only — used when embedding metrics inside a Run response."""
    p50: float
    p95: float
    p99: float
    throughput: float
    error_rate: float

    model_config = {"from_attributes": True}


class MetricsDetail(MetricsSummary):
    """Full metrics response including the raw latency array."""
    id: uuid.UUID
    run_id: uuid.UUID
    latencies: list[float]

    model_config = {"from_attributes": True}


class RunResponse(BaseModel):
    id: uuid.UUID
    target_url: str
    method: str
    num_requests: int
    concurrency: int
    status: RunStatus
    is_baseline: bool = False
    created_at: datetime
    # None until the background task finishes persisting results.
    metrics: MetricsSummary | None = None
    # Percentage deltas relative to the pinned baseline run.
    # Positive = regression, negative = improvement.
    # Only present on non-baseline runs when a baseline is set; omitted otherwise.
    delta_p50_pct: float | None = None
    delta_p95_pct: float | None = None
    delta_p99_pct: float | None = None
    delta_avg_latency_pct: float | None = None
    delta_error_rate_pct: float | None = None

    model_config = {"from_attributes": True}


class RunCreatedResponse(BaseModel):
    """Returned immediately from POST /benchmark before the run completes."""
    run_id: uuid.UUID


class PaginatedRuns(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[RunResponse]
