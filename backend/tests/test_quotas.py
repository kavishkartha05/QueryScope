import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.models.run import Run, RunStatus
from tests.conftest import login, make_code, make_run

NOW = datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc)
TODAY = NOW.replace(hour=1)          # earlier today (UTC)
YESTERDAY = NOW - timedelta(days=1, hours=1)


@pytest.fixture(autouse=True)
def _fixed_clock_and_noop_task(monkeypatch):
    monkeypatch.setattr("app.services.quotas.utc_now", lambda: NOW)

    async def _noop(run_id, req):
        return None

    monkeypatch.setattr("app.api.runs._execute_and_persist", _noop)


async def start(client, h, n=10):
    return await client.post(
        "/benchmark", headers=h,
        json={"target_url": "https://httpbin.org/get", "method": "GET", "num_requests": n, "concurrency": 2},
    )


async def user(client, label):
    code_id, code = await make_code(label)
    return code_id, await login(client, code)


async def run_count() -> int:
    async with AsyncSessionLocal() as session:
        return (await session.execute(select(func.count()).select_from(Run))).scalar_one()


# --- active runs ---------------------------------------------------------------

async def test_second_active_run_for_the_same_code_is_429(client):
    a_id, a_h = await user(client, "alpha-recruiter")
    await make_run(a_id, status=RunStatus.running, created_at=TODAY)
    resp = await start(client, a_h)
    assert resp.status_code == 429
    assert "already have a benchmark running" in resp.json()["detail"]
    assert "Retry-After" in resp.headers
    assert await run_count() == 1


async def test_pending_counts_as_active_but_finished_runs_do_not(client):
    a_id, a_h = await user(client, "alpha-recruiter")
    await make_run(a_id, status=RunStatus.done, created_at=TODAY)
    await make_run(a_id, status=RunStatus.failed, created_at=TODAY)
    assert (await start(client, a_h)).status_code == 202   # a new pending run now exists
    assert (await start(client, a_h)).status_code == 429   # pending counts


async def test_another_code_is_not_blocked_by_my_active_run(client):
    a_id, a_h = await user(client, "alpha-recruiter")
    _, b_h = await user(client, "bravo-recruiter")
    await make_run(a_id, status=RunStatus.running, created_at=TODAY)
    assert (await start(client, a_h)).status_code == 429
    assert (await start(client, b_h)).status_code == 202


async def test_at_most_two_runs_are_active_globally(client):
    a_id, a_h = await user(client, "alpha-recruiter")
    b_id, b_h = await user(client, "bravo-recruiter")
    _, c_h = await user(client, "charlie-recruiter")
    await make_run(a_id, status=RunStatus.running, created_at=TODAY)
    await make_run(b_id, status=RunStatus.pending, created_at=TODAY)
    resp = await start(client, c_h)
    assert resp.status_code == 429
    assert "busy" in resp.json()["detail"]
    # Once one of them finishes there is room again.
    async with AsyncSessionLocal() as session:
        run = (await session.execute(select(Run).where(Run.status == RunStatus.running))).scalars().one()
        run.status = RunStatus.done
        await session.commit()
    assert (await start(client, c_h)).status_code == 202


async def test_limits_are_read_from_settings(client, monkeypatch):
    monkeypatch.setattr(settings, "max_active_runs_per_code", 2)
    monkeypatch.setattr(settings, "max_concurrent_runs", 3)
    a_id, a_h = await user(client, "alpha-recruiter")
    await make_run(a_id, status=RunStatus.running, created_at=TODAY)
    assert (await start(client, a_h)).status_code == 202       # 2nd for this code allowed
    assert (await start(client, a_h)).status_code == 429       # 3rd is not


async def test_simultaneous_requests_cannot_both_pass_the_check(client):
    _, a_h = await user(client, "alpha-recruiter")
    responses = await asyncio.gather(start(client, a_h), start(client, a_h), start(client, a_h))
    codes = []
    for response in responses:
        codes.append(response.status_code)
    assert sorted(codes) == [202, 429, 429]
    assert await run_count() == 1


# --- daily budget --------------------------------------------------------------

async def test_per_code_budget_counts_todays_runs_only(client):
    a_id, a_h = await user(client, "alpha-recruiter")
    await make_run(a_id, num_requests=400, created_at=YESTERDAY)       # not today
    await make_run(a_id, num_requests=500, created_at=TODAY)
    await make_run(a_id, num_requests=500, created_at=TODAY, status=RunStatus.failed)
    await make_run(a_id, num_requests=500, created_at=TODAY)
    await make_run(a_id, num_requests=100, created_at=TODAY)
    # 1,600 used today (failed runs count too); budget 2,000.
    resp = await start(client, a_h, n=500)
    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert "Daily request budget" in detail and "1,600 of 2,000" in detail
    assert "(400 left)" in detail and "00:00 UTC" in detail
    assert 0 < int(resp.headers["Retry-After"]) <= 12 * 3600
    assert (await start(client, a_h, n=400)).status_code == 202       # exactly reaches the budget


async def test_budget_message_when_nothing_is_left(client):
    a_id, a_h = await user(client, "alpha-recruiter")
    for _ in range(4):
        await make_run(a_id, num_requests=500, created_at=TODAY)
    resp = await start(client, a_h, n=10)
    assert resp.status_code == 429
    assert "(0 left)" in resp.json()["detail"]


async def test_other_codes_budgets_are_independent(client):
    a_id, a_h = await user(client, "alpha-recruiter")
    _, b_h = await user(client, "bravo-recruiter")
    for _ in range(4):
        await make_run(a_id, num_requests=500, created_at=TODAY)
    assert (await start(client, a_h, n=10)).status_code == 429
    assert (await start(client, b_h, n=10)).status_code == 202


async def test_global_budget_counts_every_owner(client):
    a_id, _ = await user(client, "alpha-recruiter")
    _, b_h = await user(client, "bravo-recruiter")
    for _ in range(16):
        await make_run(a_id, num_requests=500, created_at=TODAY)
    # 8,000 by alpha, plus 1,800 by the demo owner = 9,800 of 10,000 today.
    await make_run(None, num_requests=1800, created_at=TODAY)
    resp = await start(client, b_h, n=300)
    assert resp.status_code == 429
    assert "capacity for today" in resp.json()["detail"]
    assert (await start(client, b_h, n=200)).status_code == 202


async def test_budgets_come_from_settings(client, monkeypatch):
    monkeypatch.setattr(settings, "daily_budget_per_code", 100)
    _, a_h = await user(client, "alpha-recruiter")
    assert (await start(client, a_h, n=101)).status_code == 429
    assert (await start(client, a_h, n=100)).status_code == 202


async def test_usage_survives_a_restart(client):
    """Nothing is kept in memory: a fresh process sees the same usage from the DB."""
    a_id, a_h = await user(client, "alpha-recruiter")
    for _ in range(4):
        await make_run(a_id, num_requests=500, created_at=TODAY)
    from app.core.db import engine

    await engine.dispose()  # drop every pooled connection, as a restart would
    assert (await start(client, a_h, n=10)).status_code == 429


# --- not enforced locally ------------------------------------------------------

async def test_quotas_are_off_when_auth_is_off(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", False)
    for _ in range(5):
        await make_run(None, status=RunStatus.running, num_requests=500, created_at=TODAY)
    assert (await start(client, {}, n=500)).status_code == 202
