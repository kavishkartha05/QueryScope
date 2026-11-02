"""
Usage limits for the hosted demo, computed from the runs table.

Nothing here is kept in memory, so the limits survive restarts and are shared
by every worker that reads the same database:
  - at most MAX_CONCURRENT_RUNS runs pending/running across the whole app
  - at most MAX_ACTIVE_RUNS_PER_CODE pending/running runs per access code
  - a daily budget (sum of num_requests since 00:00 UTC) per code and globally

The check and the insert of the new run happen under one lock (admission_lock)
so two simultaneous requests in this process cannot both pass the same check.
Across several replicas the lock is per-process, so a short race could admit one
run too many; the wall-clock limit and the reaper bound the cost of that.
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.run import Run, RunStatus

ACTIVE_STATUSES = (RunStatus.pending, RunStatus.running)


class QuotaExceeded(Exception):
    """A usage limit was hit. str(exc) is a readable message for the caller."""

    def __init__(self, message: str, retry_after_s: int) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


def utc_now() -> datetime:
    # A function (not inline) so tests can pin the clock.
    return datetime.now(timezone.utc)


def utc_day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


_lock_state: dict = {"loop": None, "lock": None}


def admission_lock() -> asyncio.Lock:
    """One lock per running event loop (a module-level Lock would bind to the first loop)."""
    loop = asyncio.get_running_loop()
    if _lock_state["loop"] is not loop:
        _lock_state["loop"] = loop
        _lock_state["lock"] = asyncio.Lock()
    return _lock_state["lock"]


async def _count_active(db: AsyncSession, code_id: uuid.UUID | None = None) -> int:
    stmt = select(func.count()).select_from(Run).where(Run.status.in_(ACTIVE_STATUSES))
    if code_id is not None:
        stmt = stmt.where(Run.access_code_id == code_id)
    return int((await db.execute(stmt)).scalar_one())


async def _requests_since(
    db: AsyncSession, since: datetime, code_id: uuid.UUID | None = None
) -> int:
    # Every run counts, whatever its final status: the traffic was (or could
    # have been) sent either way.
    stmt = select(func.coalesce(func.sum(Run.num_requests), 0)).where(Run.created_at >= since)
    if code_id is not None:
        stmt = stmt.where(Run.access_code_id == code_id)
    return int((await db.execute(stmt)).scalar_one())


async def check_quotas(db: AsyncSession, code_id: uuid.UUID | None, requested: int) -> None:
    """Raise QuotaExceeded if starting a run of `requested` requests is not allowed now."""
    if not settings.quotas_enforced:
        return

    now = utc_now()
    next_reset = utc_day_start(now) + timedelta(days=1)
    seconds_to_reset = max(1, int((next_reset - now).total_seconds()))

    if code_id is not None:
        if await _count_active(db, code_id) >= settings.max_active_runs_per_code:
            raise QuotaExceeded(
                "You already have a benchmark running. Wait for it to finish, then start another.",
                retry_after_s=15,
            )
    if await _count_active(db) >= settings.max_concurrent_runs:
        raise QuotaExceeded(
            "The demo is busy with other benchmarks right now. Please try again in a minute.",
            retry_after_s=30,
        )

    day_start = utc_day_start(now)
    if code_id is not None:
        used = await _requests_since(db, day_start, code_id)
        budget = settings.daily_budget_per_code
        if used + requested > budget:
            remaining = max(0, budget - used)
            raise QuotaExceeded(
                f"Daily request budget reached for your access code: {used:,} of {budget:,} "
                f"requests used today, and this run needs {requested:,} "
                f"({remaining:,} left). The budget resets at 00:00 UTC.",
                retry_after_s=seconds_to_reset,
            )
    used_global = await _requests_since(db, day_start)
    if used_global + requested > settings.daily_budget_global:
        raise QuotaExceeded(
            "The demo has used its request capacity for today. "
            "Please try again after 00:00 UTC.",
            retry_after_s=seconds_to_reset,
        )
