import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.models.run import Run
from app.schemas.run import BenchmarkRequest, LLMBenchmarkRequest
from tests.conftest import login, make_code

OK = {"target_url": "https://httpbin.org/get", "method": "GET", "num_requests": 10, "concurrency": 2}


@pytest.fixture(autouse=True)
def _noop_background(monkeypatch):
    async def _noop(run_id, req):
        return None

    monkeypatch.setattr("app.api.runs._execute_and_persist", _noop)


async def auth(client):
    _, code = await make_code("caps-recruiter")
    return await login(client, code)


async def run_count() -> int:
    async with AsyncSessionLocal() as session:
        return (await session.execute(select(func.count()).select_from(Run))).scalar_one()


async def post(client, h, **overrides):
    return await client.post("/benchmark", headers=h, json={**OK, **overrides})


async def test_values_at_the_caps_are_accepted(client):
    h = await auth(client)
    resp = await post(client, h, num_requests=500, concurrency=20, timeout_s=10)
    assert resp.status_code == 202


async def test_num_requests_over_the_cap_is_rejected(client):
    h = await auth(client)
    for value in [501, 1000, 10_000, 10**9]:
        resp = await post(client, h, num_requests=value)
        assert resp.status_code == 422, value
        assert "at most 500" in resp.text
    assert await run_count() == 0


async def test_concurrency_over_the_cap_is_rejected(client):
    h = await auth(client)
    for value in [21, 50, 500]:
        resp = await post(client, h, concurrency=value)
        assert resp.status_code == 422, value
        assert "at most 20" in resp.text


async def test_timeout_over_the_cap_is_rejected(client):
    h = await auth(client)
    for value in [10.01, 11, 30, 3600]:
        resp = await post(client, h, timeout_s=value)
        assert resp.status_code == 422, value
        assert "at most 10" in resp.text


async def test_non_positive_values_are_rejected(client):
    h = await auth(client)
    for field, value in [("num_requests", 0), ("num_requests", -5), ("concurrency", 0),
                         ("concurrency", -1), ("timeout_s", 0), ("timeout_s", -2)]:
        resp = await post(client, h, **{field: value})
        assert resp.status_code == 422, (field, value)


async def test_caps_are_settings_not_constants(client, monkeypatch):
    h = await auth(client)
    monkeypatch.setattr(settings, "max_num_requests", 50)
    monkeypatch.setattr(settings, "max_concurrency", 4)
    monkeypatch.setattr(settings, "max_request_timeout_s", 2.0)
    assert (await post(client, h, num_requests=51)).status_code == 422
    assert (await post(client, h, concurrency=5)).status_code == 422
    assert (await post(client, h, timeout_s=2.5)).status_code == 422
    assert (await post(client, h, num_requests=50, concurrency=4, timeout_s=2)).status_code == 202


def test_llm_request_uses_the_same_caps():
    base = {"endpoint_url": "https://api.example.com/v1/chat", "api_key": "k", "model": "m", "prompt": "p"}
    LLMBenchmarkRequest(**base, num_requests=500, concurrency=20)
    for field, value in [("num_requests", 501), ("concurrency", 21), ("timeout_s", 11)]:
        with pytest.raises(ValueError):
            LLMBenchmarkRequest(**base, **{field: value})


def test_schema_enforces_caps_without_the_api():
    # The caps live in the schema, so any code path that builds a request obeys them.
    with pytest.raises(ValueError):
        BenchmarkRequest(target_url="https://httpbin.org/get", num_requests=501, concurrency=1)
