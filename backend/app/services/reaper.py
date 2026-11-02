"""
Stale-run reaper.

A run is created as pending, the background task moves it to running, and the
task always ends it as done or failed. If the process dies or is restarted in
between (a deploy, an OOM kill), nothing is left to update the row and it would
look active forever, holding one of the limited active-run slots. This marks
such rows failed once they are older than the wall-clock limit plus a grace
period, which no live run can exceed.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.models.run import Run, RunStatus

logger = logging.getLogger(__name__)


async def reap_stale_runs(now: datetime | None = None) -> int:
    """Mark overdue pending/running runs as failed. Returns how many were changed."""
    current = now if now is not None else datetime.now(timezone.utc)
    cutoff = current - timedelta(
        seconds=settings.run_wall_clock_limit_s + settings.reaper_grace_seconds
    )
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            update(Run)
            .where(Run.status.in_([RunStatus.pending, RunStatus.running]))
            .where(Run.created_at < cutoff)
            .values(status=RunStatus.failed)
            .execution_options(synchronize_session=False)
        )
        await session.commit()
        reaped = int(result.rowcount or 0)
    if reaped:
        logger.warning("Reaper marked %d stale run(s) as failed", reaped)
    return reaped


async def reaper_loop() -> None:
    """Run reap_stale_runs forever; a failed pass is logged and retried next tick."""
    while True:
        try:
            await asyncio.sleep(settings.reaper_interval_seconds)
            await reap_stale_runs()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Stale-run reaper pass failed: %s", exc)
