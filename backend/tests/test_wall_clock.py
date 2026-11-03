import asyncio

from sqlalchemy import select

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.models.run import Run, RunStatus
from tests.conftest import login, make_code

OK = {"target_url": "https://httpbin.org/get", "method": "GET", "num_requests": 10, "concurrency": 2}


async def test_run_is_cancelled_and_failed_at_the_wall_clock_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "run_wall_clock_limit_s", 0.2)
    state = {"started": False, "cancelled": False}

    async def _slow_engine(**kwargs):
        state["started"] = True
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    monkeypatch.setattr("app.api.runs.run_benchmark", _slow_engine)
    _, code = await make_code("slow-recruiter")
    h = await login(client, code)

    loop = asyncio.get_running_loop()
    began = loop.time()
    resp = await client.post("/benchmark", headers=h, json=OK)
    elapsed = loop.time() - began

    assert resp.status_code == 202
    assert elapsed < 5  # the 30 s sleep was cut short by the 0.2 s limit
    assert state["started"] and state["cancelled"]
    async with AsyncSessionLocal() as session:
        run = (await session.execute(select(Run))).scalars().one()
        assert run.status == RunStatus.failed


async def test_a_run_inside_the_limit_still_completes(client, monkeypatch):
    monkeypatch.setattr(settings, "run_wall_clock_limit_s", 5.0)

    async def _quick_engine(**kwargs):
        return {"latencies": [12.0] * kwargs["num_requests"], "error_count": 0, "total_time": 0.1}

    monkeypatch.setattr("app.api.runs.run_benchmark", _quick_engine)
    _, code = await make_code("quick-recruiter")
    h = await login(client, code)
    assert (await client.post("/benchmark", headers=h, json=OK)).status_code == 202
    async with AsyncSessionLocal() as session:
        run = (await session.execute(select(Run))).scalars().one()
        assert run.status == RunStatus.done
