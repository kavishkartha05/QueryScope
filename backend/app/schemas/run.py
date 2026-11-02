import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator

from app.core.config import settings
from app.models.run import RunStatus


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

# The caps below are read from settings when a request is validated (not frozen
# at import time), so they are enforced server-side for every client and an
# operator can change them with an environment variable.
class _Capped(BaseModel):
    @field_validator("num_requests", check_fields=False)
    @classmethod
    def _cap_num_requests(cls, value: int) -> int:
        if value > settings.max_num_requests:
            raise ValueError(f"num_requests must be at most {settings.max_num_requests}")
        return value

    @field_validator("concurrency", check_fields=False)
    @classmethod
    def _cap_concurrency(cls, value: int) -> int:
        if value > settings.max_concurrency:
            raise ValueError(f"concurrency must be at most {settings.max_concurrency}")
        return value

    @field_validator("timeout_s", check_fields=False)
    @classmethod
    def _cap_timeout(cls, value: float | None) -> float | None:
        if value is not None and value > settings.max_request_timeout_s:
            raise ValueError(f"timeout_s must be at most {settings.max_request_timeout_s:g}")
        return value


class BenchmarkRequest(_Capped):
    target_url: HttpUrl
    method: str = Field(default="GET", max_length=10, pattern=r"^[A-Z]+$")
    num_requests: int = Field(ge=1)
    concurrency: int = Field(ge=1)
    # Per-request timeout in seconds. Omit to use the server maximum.
    timeout_s: float | None = Field(default=None, gt=0)
    headers: dict[str, str] | None = None
    body: dict | None = None
    # SLA thresholds — all optional.  Omit a field to skip that threshold.
    sla_p50_ms: float | None = Field(default=None, gt=0)
    sla_p95_ms: float | None = Field(default=None, gt=0)
    sla_p99_ms: float | None = Field(default=None, gt=0)
    sla_avg_latency_ms: float | None = Field(default=None, gt=0)
    # Accepted as a percentage (0–100); stored/compared as a percentage.
    sla_error_rate_pct: float | None = Field(default=None, ge=0, le=100)


class LLMBenchmarkRequest(_Capped):
    endpoint_url: HttpUrl
    # api_key is kept out of logs; callers must pass it per-request.
    api_key: str
    model: str
    prompt: str
    num_requests: int = Field(default=10, ge=1)
    concurrency: int = Field(default=3, ge=1)
    timeout_s: float | None = Field(default=None, gt=0)


class DiagnoseRequest(BaseModel):
    question: str


class DiagnoseResponse(BaseModel):
    diagnosis: str


# ---------------------------------------------------------------------------
# SLA schemas
# ---------------------------------------------------------------------------

class SlaConfig(BaseModel):
    """The thresholds submitted with the benchmark request."""
    p50_ms: float | None = None
    p95_ms: float | None = None
    p99_ms: float | None = None
    avg_latency_ms: float | None = None
    error_rate_pct: float | None = None


class SlaThresholdResult(BaseModel):
    """Evaluation outcome for a single threshold."""
    metric: str                        # e.g. "p95_ms"
    target: float                      # configured threshold
    actual: float                      # measured value
    status: Literal["pass", "fail"]
    delta: float                       # actual - target (positive = over budget)


class SlaResult(BaseModel):
    """Aggregated SLA evaluation result stored on the run."""
    # None only when no thresholds were configured (SlaConfig was all-None).
    status: Literal["pass", "fail"] | None
    thresholds: list[SlaThresholdResult]


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
    # SLA config and result — absent when no thresholds were configured.
    sla_config: SlaConfig | None = None
    sla_result: SlaResult | None = None

    model_config = {"from_attributes": True}


class RunCreatedResponse(BaseModel):
    """Returned immediately from POST /benchmark before the run completes."""
    run_id: uuid.UUID


class PaginatedRuns(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[RunResponse]
