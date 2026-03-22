import uuid
from typing import Annotated

import numpy as np
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.run import Metrics, Run, RunStatus
from app.schemas.run import (
    BenchmarkRequest,
    MetricsDetail,
    PaginatedRuns,
    RunCreatedResponse,
    RunResponse,
)
from app.services.runner import run_benchmark

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
            arr = np.array(latencies, dtype=float)

            metrics = Metrics(
                run_id=run_id,
                latencies=latencies,
                # numpy percentile gives more accurate results than a sorted
                # index approximation, consistent with how the frontend will
                # display tail latency.
                p50=float(np.percentile(arr, 50)),
                p95=float(np.percentile(arr, 95)),
                p99=float(np.percentile(arr, 99)),
                throughput=req.num_requests / result["total_time"],
                error_rate=result["error_count"] / req.num_requests,
            )
            session.add(metrics)

            run.status = RunStatus.done
            await session.commit()

        except Exception:
            # Mark failed so the client isn't left polling a "running" run.
            run.status = RunStatus.failed
            await session.commit()
            raise


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

@router.get("/runs", response_model=PaginatedRuns)
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

    return PaginatedRuns(
        total=total,
        offset=offset,
        limit=limit,
        items=[_run_to_response(r) for r in runs],
    )


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
# Helpers
# ---------------------------------------------------------------------------

def _run_to_response(run: Run) -> RunResponse:
    """
    Map ORM Run → RunResponse.

    metrics is a list on the ORM side (one run could have multiple snapshots
    in theory); we take the first entry for the summary because we only ever
    write one Metrics row per run today.
    """
    from app.schemas.run import MetricsSummary

    metrics_summary = None
    if run.metrics:
        m = run.metrics[0]
        metrics_summary = MetricsSummary.model_validate(m)

    return RunResponse(
        id=run.id,
        target_url=run.target_url,
        method=run.method,
        num_requests=run.num_requests,
        concurrency=run.concurrency,
        status=run.status,
        created_at=run.created_at,
        metrics=metrics_summary,
    )
