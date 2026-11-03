import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.main import app
from app.models.run import Run, RunStatus
from app.services.reaper import reap_stale_runs, reaper_loop
from tests.conftest import make_run

NOW = datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)
# Default limit is 60 s plus a 120 s grace period: 180 s.


def ago(seconds: float) -> datetime:
    return NOW - timedelta(seconds=seconds)


async def status_of(run_id) -> RunStatus:
    async with AsyncSessionLocal() as session:
        return (await session.execute(select(Run.status).where(Run.id == run_id))).scalar_one()


async def test_overdue_pending_and_running_runs_are_failed():
    pending = await make_run(None, status=RunStatus.pending, created_at=ago(600))
    running = await make_run(None, status=RunStatus.running, created_at=ago(3600))
    assert await reap_stale_runs(now=NOW) == 2
    assert await status_of(pending) == RunStatus.failed
    assert await status_of(running) == RunStatus.failed


async def test_runs_inside_the_limit_plus_grace_are_left_alone():
    fresh_running = await make_run(None, status=RunStatus.running, created_at=ago(30))
    fresh_pending = await make_run(None, status=RunStatus.pending, created_at=ago(179))
    assert await reap_stale_runs(now=NOW) == 0
    assert await status_of(fresh_running) == RunStatus.running
    assert await status_of(fresh_pending) == RunStatus.pending


async def test_boundary_is_limit_plus_grace():
    just_over = await make_run(None, status=RunStatus.running, created_at=ago(181))
    assert await reap_stale_runs(now=NOW) == 1
    assert await status_of(just_over) == RunStatus.failed


async def test_finished_runs_are_never_touched():
    done = await make_run(None, status=RunStatus.done, created_at=ago(9999))
    failed = await make_run(None, status=RunStatus.failed, created_at=ago(9999))
    assert await reap_stale_runs(now=NOW) == 0
    assert await status_of(done) == RunStatus.done
    assert await status_of(failed) == RunStatus.failed


async def test_it_is_idempotent_and_frees_the_active_slot():
    owner = await make_run(None, status=RunStatus.running, created_at=ago(900))
    assert await reap_stale_runs(now=NOW) == 1
    assert await reap_stale_runs(now=NOW) == 0
    assert await status_of(owner) == RunStatus.failed


async def test_thresholds_come_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "run_wall_clock_limit_s", 10.0)
    monkeypatch.setattr(settings, "reaper_grace_seconds", 5.0)
    stale = await make_run(None, status=RunStatus.running, created_at=ago(16))
    live = await make_run(None, status=RunStatus.running, created_at=ago(14))
    assert await reap_stale_runs(now=NOW) == 1
    assert await status_of(stale) == RunStatus.failed
    assert await status_of(live) == RunStatus.running


async def test_periodic_loop_reaps_runs_that_become_stale_later(monkeypatch):
    monkeypatch.setattr(settings, "reaper_interval_seconds", 0.05)
    task = asyncio.create_task(reaper_loop())
    try:
        # Created after the loop started, already overdue by the real clock.
        stuck = await make_run(None, status=RunStatus.running, age_minutes=30)
        for _ in range(60):
            if await status_of(stuck) == RunStatus.failed:
                break
            await asyncio.sleep(0.05)
        assert await status_of(stuck) == RunStatus.failed
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def test_loop_survives_a_failing_pass(monkeypatch):
    monkeypatch.setattr(settings, "reaper_interval_seconds", 0.02)
    calls = {"n": 0}

    async def _flaky(now=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database unavailable")
        return 0

    monkeypatch.setattr("app.services.reaper.reap_stale_runs", _flaky)
    task = asyncio.create_task(reaper_loop())
    await asyncio.sleep(0.3)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert calls["n"] >= 2


async def test_startup_reaps_and_shutdown_stops_the_loop():
    stuck = await make_run(None, status=RunStatus.running, age_minutes=30)
    live = await make_run(None, status=RunStatus.running, age_minutes=0)
    async with app.router.lifespan_context(app):
        assert await status_of(stuck) == RunStatus.failed   # reaped by the startup pass
        assert await status_of(live) == RunStatus.running
    # Leaving the context cancelled the periodic task without errors.
