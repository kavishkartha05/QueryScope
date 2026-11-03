import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.models.run import Run, RunStatus
from tests.conftest import login, make_code

BODY = {"method": "GET", "num_requests": 5, "concurrency": 2}


@pytest.fixture(autouse=True)
def _allowlist_off(monkeypatch):
    monkeypatch.setattr(settings, "target_allowlist_enabled", False)


async def headers_for(client, label="alpha-recruiter"):
    code_id, code = await make_code(label)
    return code_id, await login(client, code)


async def run_count() -> int:
    async with AsyncSessionLocal() as session:
        return (await session.execute(select(func.count()).select_from(Run))).scalar_one()


async def test_unsafe_targets_get_422_and_create_no_run(client, dns, monkeypatch):
    dns["localhost"] = ["127.0.0.1"]
    dns["internal.example.test"] = ["10.0.0.5"]
    dns["v6.example.test"] = ["::1"]
    _, h = await headers_for(client)
    started = []

    async def _spy(run_id, req):
        started.append(run_id)

    monkeypatch.setattr("app.api.runs._execute_and_persist", _spy)
    urls = [
        "http://127.0.0.1/", "http://localhost:8000/", "http://[::1]/", "http://[::ffff:127.0.0.1]/",
        "http://2130706433/", "http://017700000001/", "http://0x7f000001/", "http://127.1/",
        "http://10.0.0.1/", "http://172.16.0.9/", "http://192.168.1.1/", "http://169.254.169.254/latest/",
        "http://100.64.0.1/", "http://224.0.0.1/", "http://0.0.0.0/", "http://[fc00::1]/", "http://[fe80::1]/",
        "http://internal.example.test/", "http://v6.example.test/", "http://nxdomain.example.test/",
        "ftp://example.com/", "file:///etc/passwd", "gopher://example.com/",
    ]
    for url in urls:
        resp = await client.post("/benchmark", headers=h, json={"target_url": url, **BODY})
        assert resp.status_code == 422, url
        assert resp.json()["detail"]
    assert started == []
    assert await run_count() == 0


async def test_error_detail_does_not_leak_addresses(client, dns):
    dns["internal.example.test"] = ["10.9.8.7"]
    _, h = await headers_for(client)
    resp = await client.post("/benchmark", headers=h, json={"target_url": "http://internal.example.test/", **BODY})
    assert resp.status_code == 422
    assert "10.9.8.7" not in resp.text


async def test_public_target_is_accepted(client, monkeypatch):
    _, h = await headers_for(client)

    async def _noop(run_id, req):
        return None

    monkeypatch.setattr("app.api.runs._execute_and_persist", _noop)
    resp = await client.post("/benchmark", headers=h, json={"target_url": "https://httpbin.org/get", **BODY})
    assert resp.status_code == 202
    assert await run_count() == 1


async def test_background_run_connects_only_to_the_validated_addresses(client, dns, monkeypatch):
    dns["httpbin.org"] = ["93.184.216.34"]
    _, h = await headers_for(client)
    seen = {}

    async def _fake_run(**kwargs):
        seen.update(kwargs)
        return {"latencies": [10.0] * kwargs["num_requests"], "error_count": 0, "total_time": 0.5}

    monkeypatch.setattr("app.api.runs.run_benchmark", _fake_run)
    resp = await client.post("/benchmark", headers=h, json={"target_url": "https://httpbin.org/get", **BODY})
    assert resp.status_code == 202
    assert seen["pins"] == {"httpbin.org": ["93.184.216.34"]}
    assert seen["timeout_s"] == settings.max_request_timeout_s
    async with AsyncSessionLocal() as session:
        run = (await session.execute(select(Run))).scalars().one()
        assert run.status == RunStatus.done


async def test_dns_rebinding_between_accept_and_connect_fails_the_run(client, monkeypatch):
    """First lookup is public (request accepted); the second, at connect time, is internal."""
    answers = [["93.184.216.34"], ["169.254.169.254"]]

    async def _rebinding(host, port):
        return answers.pop(0) if len(answers) > 1 else answers[0]

    monkeypatch.setattr("app.services.ssrf._resolve_host", _rebinding)
    connected = []

    async def _must_not_connect(**kwargs):
        connected.append(kwargs)
        return {"latencies": [], "error_count": 0, "total_time": 0.0}

    monkeypatch.setattr("app.api.runs.run_benchmark", _must_not_connect)
    _, h = await headers_for(client)
    resp = await client.post("/benchmark", headers=h, json={"target_url": "https://httpbin.org/get", **BODY})
    assert resp.status_code == 202
    assert connected == []
    async with AsyncSessionLocal() as session:
        run = (await session.execute(select(Run))).scalars().one()
        assert run.status == RunStatus.failed


async def test_allowlist_applies_through_the_api(client, dns, monkeypatch):
    monkeypatch.setattr(settings, "target_allowlist_enabled", None)  # follow auth (on)
    monkeypatch.setattr(settings, "allowed_target_hosts", "httpbin.org")
    dns["httpbin.org.evil.com"] = ["93.184.216.34"]
    _, h = await headers_for(client)
    resp = await client.post("/benchmark", headers=h, json={"target_url": "https://httpbin.org.evil.com/", **BODY})
    assert resp.status_code == 422
    assert "allowlist" in resp.json()["detail"]
    assert await run_count() == 0
