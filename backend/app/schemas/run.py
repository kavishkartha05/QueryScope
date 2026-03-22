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
    created_at: datetime
    # None until the background task finishes persisting results.
    metrics: MetricsSummary | None = None

    model_config = {"from_attributes": True}


class RunCreatedResponse(BaseModel):
    """Returned immediately from POST /benchmark before the run completes."""
    run_id: uuid.UUID


class PaginatedRuns(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[RunResponse]
