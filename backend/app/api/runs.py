import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.run import Metrics, Run, RunStatus
from app.schemas.run import (
    BenchmarkRequest,
    DiagnoseRequest,
    DiagnoseResponse,
    LLMBenchmarkRequest,
    MetricsDetail,
    PaginatedRuns,
    RunCreatedResponse,
    RunResponse,
    SlaConfig,
    SlaResult,
)
from app.services.aggregator import compute_metrics
from app.services.indexer import index_run
from app.services.runner import run_benchmark, run_llm_benchmark

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/benchmark", tags=["runs"])

# Reusable dependency alias for brevity in signatures.
DB = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------

async def _execute_and_persist(run_id: uuid.UUID, req: BenchmarkRequest) -> None:
    """
    Called by FastAPI's BackgroundTasks after the HTTP response is sent.

    Opens its own DB session because the request-scoped session passed to the
    route handler is already closed by the time this runs.
    """
    logger.info("Background task started for run %s", run_id)

    from app.core.db import AsyncSessionLocal  # local import avoids circular at module load

    async with AsyncSessionLocal() as session:
        run = await session.get(Run, run_id)
        if run is None:
            return  # defensive: shouldn't happen

        try:
            run.status = RunStatus.running
            await session.commit()

            result = await run_benchmark(
                target_url=str(req.target_url),
                method=req.method,
                num_requests=req.num_requests,
                concurrency=req.concurrency,
                headers=req.headers,
                body=req.body,
            )

            latencies = result["latencies"]
            agg = compute_metrics(
                latencies=latencies,
                total_time=result["total_time"],
                num_requests=req.num_requests,
                error_count=result["error_count"],
            )

            metrics = Metrics(
                run_id=run_id,
                latencies=latencies,
                **agg,
            )
            session.add(metrics)

            # SLA evaluation — only when at least one threshold was provided.
            has_sla = any([
                req.sla_p50_ms is not None,
                req.sla_p95_ms is not None,
                req.sla_p99_ms is not None,
                req.sla_avg_latency_ms is not None,
                req.sla_error_rate_pct is not None,
            ])
            if has_sla:
                from app.services.sla import evaluate_sla

                sla_config = SlaConfig(
                    p50_ms=req.sla_p50_ms,
                    p95_ms=req.sla_p95_ms,
                    p99_ms=req.sla_p99_ms,
                    avg_latency_ms=req.sla_avg_latency_ms,
                    error_rate_pct=req.sla_error_rate_pct,
                )
                avg_latency_ms = (
                    sum(latencies) / len(latencies) if latencies else None
                )
                # error_rate from aggregator is stored as 0–1 fraction;
                # SLA input and comparison are both in percentage (0–100).
                sla_result = evaluate_sla(
                    config=sla_config,
                    p50=agg["p50"],
                    p95=agg["p95"],
                    p99=agg["p99"],
                    avg_latency_ms=avg_latency_ms,
                    error_rate_pct=agg["error_rate"] * 100,
                )
                run.sla_config = sla_config.model_dump(exclude_none=True)
                run.sla_result = sla_result.model_dump()
                logger.info(
                    "SLA evaluation for run %s: %s", run_id, sla_result.status
                )

            run.status = RunStatus.done
            await session.commit()

            logger.info("Run %s completed, status=done", run_id)

            # Indexing is best-effort: a transient Azure Search or OpenAI error
            # must not roll back a completed benchmark or change its status.
            # The run result is already durable in Postgres; the search index
            # can be backfilled later if needed.
            logger.info("About to index run %s", run_id)
            try:
                await index_run(
                    run_id=str(run.id),
                    target_url=run.target_url,
                    method=run.method,
                    num_requests=run.num_requests,
                    p50=metrics.p50,
                    p95=metrics.p95,
                    p99=metrics.p99,
                    throughput=metrics.throughput,
                    error_rate=metrics.error_rate,
                    created_at=run.created_at,
                )
            except Exception as exc:
                logger.warning("Indexing failed for run %s: %s", run.id, exc)
            logger.info("Indexing block completed for run %s", run_id)

        except Exception as bg_exc:
            logger.exception("Background task failed for run %s: %s", run_id, bg_exc)
            run.status = RunStatus.failed
            await session.commit()


# ---------------------------------------------------------------------------
# POST /benchmark
# ---------------------------------------------------------------------------

@router.post("", response_model=RunCreatedResponse, status_code=202)
async def create_benchmark(
    req: BenchmarkRequest,
    background_tasks: BackgroundTasks,
    db: DB,
) -> RunCreatedResponse:
    run = Run(
        target_url=str(req.target_url),
        method=req.method.upper(),
        num_requests=req.num_requests,
        concurrency=req.concurrency,
    )
    db.add(run)
    # Flush to get the DB-assigned id without committing the transaction;
    # commit happens here so the row is visible to the background task's
    # separate session before that task starts.
    await db.commit()
    await db.refresh(run)

    # BackgroundTasks runs after the response is sent but inside the same
    # process — no broker needed for week-1 simplicity (see CLAUDE.md).
    background_tasks.add_task(_execute_and_persist, run.id, req)

    return RunCreatedResponse(run_id=run.id)


# ---------------------------------------------------------------------------
# GET /runs
# ---------------------------------------------------------------------------

@router.get("/runs", response_model=PaginatedRuns, response_model_exclude_none=True)
async def list_runs(
    db: DB,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedRuns:
    total_result = await db.execute(select(func.count()).select_from(Run))
    total = total_result.scalar_one()

    runs_result = await db.execute(
        select(Run).order_by(Run.created_at.desc()).offset(offset).limit(limit)
    )
    # unique() is required after selectin-loaded relationships to de-duplicate
    # the joined rows that SQLAlchemy emits internally.
    runs = runs_result.scalars().unique().all()

    # Fetch the current baseline so deltas can be computed for every other run.
    baseline_result = await db.execute(
        select(Run).where(Run.is_baseline == True)  # noqa: E712
    )
    baseline = baseline_result.scalars().first()
    baseline_metrics = baseline.metrics[0] if (baseline and baseline.metrics) else None

    return PaginatedRuns(
        total=total,
        offset=offset,
        limit=limit,
        items=[_run_to_response(r, baseline_metrics=baseline_metrics) for r in runs],
    )


# ---------------------------------------------------------------------------
# GET /runs/baseline  — must be defined before /runs/{run_id} so that the
# static path segment "baseline" is matched first.
# ---------------------------------------------------------------------------

@router.get("/runs/baseline", response_model=RunResponse)
async def get_baseline_run(db: DB) -> RunResponse:
    result = await db.execute(
        select(Run).where(Run.is_baseline == True)  # noqa: E712
    )
    baseline = result.scalars().first()
    if baseline is None:
        raise HTTPException(status_code=404, detail="No baseline run is set")
    return _run_to_response(baseline)


# ---------------------------------------------------------------------------
# PATCH /runs/{run_id}/baseline
# ---------------------------------------------------------------------------

@router.patch("/runs/{run_id}/baseline", response_model=RunResponse)
async def set_baseline(run_id: uuid.UUID, db: DB) -> RunResponse:
    run = await db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.is_baseline:
        raise HTTPException(status_code=400, detail="Run is already the baseline")

    # Clear any existing baseline before setting the new one — only one may
    # exist at a time. Using a bulk UPDATE avoids a separate SELECT + loop.
    # synchronize_session=False skips the in-memory cache update; the commit
    # and refresh below make the session consistent again.
    await db.execute(
        update(Run)
        .where(Run.is_baseline == True)  # noqa: E712
        .values(is_baseline=False)
        .execution_options(synchronize_session=False)
    )
    run.is_baseline = True
    await db.commit()
    await db.refresh(run)
    return _run_to_response(run)


# ---------------------------------------------------------------------------
# GET /runs/{run_id}
# ---------------------------------------------------------------------------

@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(run_id: uuid.UUID, db: DB) -> RunResponse:
    run = await db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_to_response(run)


# ---------------------------------------------------------------------------
# GET /runs/{run_id}/metrics
# ---------------------------------------------------------------------------

@router.get("/runs/{run_id}/metrics", response_model=MetricsDetail)
async def get_run_metrics(run_id: uuid.UUID, db: DB) -> MetricsDetail:
    result = await db.execute(
        select(Metrics).where(Metrics.run_id == run_id)
    )
    metrics = result.scalars().first()
    if metrics is None:
        raise HTTPException(
            status_code=404,
            detail="Metrics not found — run may still be in progress",
        )
    return MetricsDetail.model_validate(metrics)


# ---------------------------------------------------------------------------
# POST /benchmark/llm
# ---------------------------------------------------------------------------

async def _execute_llm_benchmark(run_id: str, req: LLMBenchmarkRequest) -> None:
    """
    Background task for LLM benchmarking. Results are logged rather than
    persisted to the Metrics table — LLM metrics (TTFT, tokens/sec) have a
    different shape from REST latencies and don't fit the existing schema.
    Persistence can be added in a follow-up once the schema is extended.
    """
    import numpy as np

    logger.info("LLM benchmark task started for run_id=%s", run_id)
    try:
        result = await run_llm_benchmark(
            endpoint_url=str(req.endpoint_url),
            api_key=req.api_key,
            model=req.model,
            prompt=req.prompt,
            num_requests=req.num_requests,
            concurrency=req.concurrency,
        )

        ttft = np.array(result["ttft_latencies"], dtype=float)
        total = np.array(result["total_latencies"], dtype=float)
        tps_list = result["tokens_per_second_list"]

        avg_tps = float(np.mean(tps_list)) if tps_list else 0.0

        logger.info(
            "LLM benchmark run_id=%s complete | "
            "TTFT p50=%.1fms p95=%.1fms p99=%.1fms | "
            "total_time p50=%.1fms p95=%.1fms p99=%.1fms | "
            "avg_tokens_per_sec=%.2f | errors=%d",
            run_id,
            float(np.percentile(ttft, 50)),
            float(np.percentile(ttft, 95)),
            float(np.percentile(ttft, 99)),
            float(np.percentile(total, 50)),
            float(np.percentile(total, 95)),
            float(np.percentile(total, 99)),
            avg_tps,
            result["error_count"],
        )
    except Exception as exc:
        logger.exception("LLM benchmark task failed for run_id=%s: %s", run_id, exc)


@router.post("/llm", response_model=RunCreatedResponse, status_code=202)
async def create_llm_benchmark(
    req: LLMBenchmarkRequest,
    background_tasks: BackgroundTasks,
) -> RunCreatedResponse:
    # Generate a client-visible run_id without a DB row — LLM runs aren't
    # persisted to the runs table yet. The id still lets callers correlate
    # log lines with the request that triggered them.
    import uuid as _uuid

    run_id = str(_uuid.uuid4())
    background_tasks.add_task(_execute_llm_benchmark, run_id, req)
    return RunCreatedResponse(run_id=_uuid.UUID(run_id))


# ---------------------------------------------------------------------------
# DELETE /benchmark/runs
# ---------------------------------------------------------------------------

@router.delete("/runs", status_code=200)
async def reset_session(db: DB) -> dict[str, str]:
    # Bulk ORM delete: issues a single DELETE FROM runs to the DB.
    # The DB-level ondelete="CASCADE" on metrics.run_id handles removing
    # all child metrics rows — ORM-level cascade doesn't fire for bulk deletes,
    # so relying on the FK cascade here is intentional and correct.
    await db.execute(delete(Run))
    await db.commit()
    return {"message": "Session reset successfully"}


# ---------------------------------------------------------------------------
# POST /diagnose
# ---------------------------------------------------------------------------

@router.post("/diagnose", response_model=DiagnoseResponse)
async def diagnose_run(req: DiagnoseRequest, db: DB) -> DiagnoseResponse:
    # Local import keeps rca.py's heavy LangChain/LlamaIndex imports from
    # loading at startup — they're only needed when this endpoint is hit.
    from app.services.rca import diagnose

    result = await diagnose(req.question, db=db)
    return DiagnoseResponse(diagnosis=result)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pct_delta(current: float, baseline: float) -> float:
    """Return percentage change of current vs baseline (positive = regression).
    Returns 0.0 when baseline is zero to avoid division-by-zero."""
    if baseline == 0:
        return 0.0
    return (current - baseline) / baseline * 100.0


def _avg(latencies: list[float]) -> float:
    """Mean latency; returns 0.0 for empty lists."""
    return sum(latencies) / len(latencies) if latencies else 0.0


def _run_to_response(run: Run, baseline_metrics: "Metrics | None" = None) -> RunResponse:
    """
    Map ORM Run → RunResponse.

    metrics is a list on the ORM side (one run could have multiple snapshots
    in theory); we take the first entry for the summary because we only ever
    write one Metrics row per run today.

    When baseline_metrics is provided and this run is not itself the baseline,
    percentage deltas are computed and included in the response.
    """
    from app.schemas.run import MetricsSummary

    metrics_summary = None
    if run.metrics:
        m = run.metrics[0]
        metrics_summary = MetricsSummary.model_validate(m)

    # Compute deltas only for non-baseline runs that have completed metrics
    # and when a baseline with metrics exists.
    delta_p50_pct = None
    delta_p95_pct = None
    delta_p99_pct = None
    delta_avg_latency_pct = None
    delta_error_rate_pct = None

    if baseline_metrics and not run.is_baseline and run.metrics:
        m = run.metrics[0]
        delta_p50_pct = _pct_delta(m.p50, baseline_metrics.p50)
        delta_p95_pct = _pct_delta(m.p95, baseline_metrics.p95)
        delta_p99_pct = _pct_delta(m.p99, baseline_metrics.p99)
        delta_avg_latency_pct = _pct_delta(
            _avg(m.latencies), _avg(baseline_metrics.latencies)
        )
        delta_error_rate_pct = _pct_delta(m.error_rate, baseline_metrics.error_rate)

    # Deserialise SLA JSON dicts back to typed Pydantic models.
    sla_config_obj = (
        SlaConfig.model_validate(run.sla_config) if run.sla_config else None
    )
    sla_result_obj = (
        SlaResult.model_validate(run.sla_result) if run.sla_result else None
    )

    return RunResponse(
        id=run.id,
        target_url=run.target_url,
        method=run.method,
        num_requests=run.num_requests,
        concurrency=run.concurrency,
        status=run.status,
        is_baseline=run.is_baseline,
        created_at=run.created_at,
        metrics=metrics_summary,
        delta_p50_pct=delta_p50_pct,
        delta_p95_pct=delta_p95_pct,
        delta_p99_pct=delta_p99_pct,
        delta_avg_latency_pct=delta_avg_latency_pct,
        delta_error_rate_pct=delta_error_rate_pct,
        sla_config=sla_config_obj,
        sla_result=sla_result_obj,
    )
