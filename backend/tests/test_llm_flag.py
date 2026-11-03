import pytest

from app.api import runs as runs_module
from app.core.config import settings
from app.schemas.run import LLMBenchmarkRequest
from tests.conftest import login, make_code

# Captured at import time, before the autouse fixture replaces the task.
REAL_LLM_TASK = runs_module._execute_llm_benchmark

BODY = {
    "endpoint_url": "https://httpbin.org/post", "api_key": "test-key-not-real", "model": "m",
    "prompt": "hello", "num_requests": 3, "concurrency": 2,
}


@pytest.fixture(autouse=True)
def _tasks_off(monkeypatch):
    async def _noop(run_id, req):
        return None

    monkeypatch.setattr("app.api.runs._execute_llm_benchmark", _noop)


async def auth(client):
    _, code = await make_code("llm-recruiter")
    return await login(client, code)


async def test_route_is_404_when_auth_is_on_and_flag_is_unset(client):
    h = await auth(client)
    resp = await client.post("/benchmark/llm", headers=h, json=BODY)
    assert resp.status_code == 404
    # Same body as a route that does not exist.
    unknown = await client.post("/benchmark/does-not-exist", headers=h, json=BODY)
    assert resp.json() == unknown.json()


async def test_route_is_404_when_flag_is_false(client, monkeypatch):
    monkeypatch.setattr(settings, "llm_benchmark_enabled", False)
    h = await auth(client)
    assert (await client.post("/benchmark/llm", headers=h, json=BODY)).status_code == 404


async def test_route_still_requires_a_session_first(client):
    assert (await client.post("/benchmark/llm", json=BODY)).status_code == 401


async def test_route_works_when_the_flag_is_on(client, monkeypatch):
    monkeypatch.setattr(settings, "llm_benchmark_enabled", True)
    h = await auth(client)
    resp = await client.post("/benchmark/llm", headers=h, json=BODY)
    assert resp.status_code == 202
    assert "run_id" in resp.json()


async def test_flag_defaults_to_on_when_auth_is_off(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", False)
    monkeypatch.setattr(settings, "llm_benchmark_enabled", None)
    assert (await client.post("/benchmark/llm", json=BODY)).status_code == 202
    monkeypatch.setattr(settings, "llm_benchmark_enabled", False)
    assert (await client.post("/benchmark/llm", json=BODY)).status_code == 404


async def test_enabled_route_applies_ssrf_allowlist_and_caps(client, dns, monkeypatch):
    monkeypatch.setattr(settings, "llm_benchmark_enabled", True)
    monkeypatch.setattr(settings, "target_allowlist_enabled", None)
    monkeypatch.setattr(settings, "allowed_target_hosts", "httpbin.org,internal.example.test")
    dns["internal.example.test"] = ["10.0.0.5"]
    h = await auth(client)
    for url in ["http://169.254.169.254/v1/chat", "http://internal.example.test/v1/chat",
                "https://example.com/v1/chat", "ftp://httpbin.org/x"]:
        resp = await client.post("/benchmark/llm", headers=h, json={**BODY, "endpoint_url": url})
        assert resp.status_code == 422, url
    assert (await client.post("/benchmark/llm", headers=h, json={**BODY, "num_requests": 501})).status_code == 422
    assert (await client.post("/benchmark/llm", headers=h, json={**BODY, "concurrency": 21})).status_code == 422


async def test_background_task_pins_connections_and_rechecks_dns(dns, monkeypatch):
    req = LLMBenchmarkRequest(**BODY)
    seen = []

    async def _fake_engine(**kwargs):
        seen.append(kwargs)
        return {"ttft_latencies": [1.0], "total_latencies": [2.0], "tokens_per_second_list": [3.0], "error_count": 0}

    monkeypatch.setattr("app.api.runs.run_llm_benchmark", _fake_engine)
    await REAL_LLM_TASK("run-1", req)
    assert seen[0]["pins"] == {"httpbin.org": ["93.184.216.34"]}
    assert seen[0]["timeout_s"] == settings.max_request_timeout_s

    # DNS now answers with the metadata address: nothing may be sent.
    dns["httpbin.org"] = ["169.254.169.254"]
    seen.clear()
    await REAL_LLM_TASK("run-2", req)
    assert seen == []
