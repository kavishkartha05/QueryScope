import asyncio

import httpx
import pytest

import server


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(server.LIMITS, "max_latency_ms", 2000.0)
    monkeypatch.setattr(server.LIMITS, "max_inflight", 50)
    server._state["inflight"] = 0


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://demo") as c:
        yield c


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200 and resp.json() == {"status": "ok"}


async def test_defaults_answer_immediately_with_ok(client):
    resp = await client.get("/work")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "delay_ms": 0.0}


async def test_post_is_accepted_and_the_body_is_ignored(client):
    resp = await client.post("/work", json={"anything": "here"})
    assert resp.status_code == 200


async def test_latency_is_applied(client):
    loop = asyncio.get_running_loop()
    began = loop.time()
    resp = await client.get("/work?latency_ms=150")
    assert resp.status_code == 200
    assert loop.time() - began >= 0.14
    assert resp.json()["delay_ms"] == 150.0


async def test_jitter_adds_a_bounded_random_delay(client, monkeypatch):
    monkeypatch.setattr(server._rng, "random", lambda: 0.5)
    resp = await client.get("/work?latency_ms=20&jitter_ms=40")
    assert resp.json()["delay_ms"] == 40.0   # 20 + 0.5 * 40


async def test_error_rate_one_always_fails_with_the_chosen_status(client):
    for status in (500, 502, 503, 504):
        resp = await client.get(f"/work?error_rate=1&error_status={status}")
        assert resp.status_code == status
        assert resp.json() == {"ok": False}


async def test_error_rate_zero_never_fails(client):
    for _ in range(100):
        assert (await client.get("/work?error_rate=0")).status_code == 200


async def test_error_rate_is_a_probability(client, monkeypatch):
    draws = iter([0.01, 0.99, 0.30, 0.04])
    monkeypatch.setattr(server._rng, "random", lambda: next(draws))
    statuses = []
    for _ in range(4):
        statuses.append((await client.get("/work?error_rate=0.05")).status_code)
    assert statuses == [500, 200, 200, 500]


async def test_values_beyond_the_caps_are_rejected_not_clamped(client):
    for query in [
        "latency_ms=2001", "latency_ms=1500&jitter_ms=600", "jitter_ms=99999", "latency_ms=-1",
        "jitter_ms=-5", "error_rate=1.01", "error_rate=-0.1", "error_status=200", "error_status=404",
        "error_status=500.5", "latency_ms=abc", "latency_ms=nan", "latency_ms=inf", "error_rate=nan",
    ]:
        resp = await client.get(f"/work?{query}")
        assert resp.status_code == 422, query


async def test_the_latency_cap_is_a_setting(client, monkeypatch):
    monkeypatch.setattr(server.LIMITS, "max_latency_ms", 100.0)
    assert (await client.get("/work?latency_ms=101")).status_code == 422
    assert (await client.get("/work?latency_ms=100")).status_code == 200


async def test_requests_beyond_the_inflight_cap_get_503_immediately(client, monkeypatch):
    monkeypatch.setattr(server.LIMITS, "max_inflight", 2)
    slow = []
    for _ in range(2):
        slow.append(asyncio.create_task(client.get("/work?latency_ms=400")))
    await asyncio.sleep(0.1)   # both are now sleeping inside the handler
    loop = asyncio.get_running_loop()
    began = loop.time()
    extra = await client.get("/work?latency_ms=400")
    assert extra.status_code == 503
    assert extra.headers["retry-after"] == "1"
    assert loop.time() - began < 0.2          # refused at once, not queued
    for response in await asyncio.gather(*slow):
        assert response.status_code == 200
    assert server._state["inflight"] == 0     # slots are released
    assert (await client.get("/work")).status_code == 200


async def test_inflight_is_released_when_a_request_errors(client):
    for _ in range(5):
        await client.get("/work?error_rate=1")
    assert server._state["inflight"] == 0


async def test_a_declared_large_body_is_refused(client):
    resp = await client.post("/work", content=b"x" * 20_000)
    assert resp.status_code == 413


async def test_other_methods_and_paths_are_not_available(client):
    for method in ("PUT", "DELETE", "PATCH"):
        assert (await client.request(method, "/work")).status_code == 405
    for path in ("/docs", "/redoc", "/openapi.json", "/", "/admin"):
        assert (await client.get(path)).status_code == 404


async def test_nothing_from_the_request_is_echoed(client):
    resp = await client.get("/work?latency_ms=1&x=<script>alert(1)</script>")
    assert "script" not in resp.text
