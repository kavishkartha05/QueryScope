from app.core.config import settings
from tests.conftest import login, make_code, make_run


async def auth(client, label="cfg-recruiter"):
    code_id, code = await make_code(label)
    return code_id, await login(client, code)


async def test_config_requires_a_session(client):
    assert (await client.get("/config")).status_code == 401


async def test_config_reports_caps_targets_and_flags(client, monkeypatch):
    monkeypatch.setattr(settings, "allowed_target_hosts", "httpbin.org,demo.example.com")
    monkeypatch.setattr(settings, "demo_target_url", "https://demo.example.com/work")
    monkeypatch.setattr(settings, "llm_benchmark_enabled", None)
    _, h = await auth(client)
    body = (await client.get("/config", headers=h)).json()

    assert body["caps"]["max_num_requests"] == settings.max_num_requests
    assert body["caps"]["max_concurrency"] == settings.max_concurrency
    assert body["caps"]["max_request_timeout_s"] == settings.max_request_timeout_s
    assert body["targets"] == [
        {"label": "httpbin.org", "url": "https://httpbin.org/get"},
        {"label": "QueryScope demo target", "url": "https://demo.example.com/work"},
    ]
    assert body["allow_custom_target"] is False
    assert body["llm_benchmark_enabled"] is False


async def test_config_follows_the_llm_flag(client, monkeypatch):
    monkeypatch.setattr(settings, "llm_benchmark_enabled", True)
    _, h = await auth(client)
    assert (await client.get("/config", headers=h)).json()["llm_benchmark_enabled"] is True


async def test_config_allows_custom_target_when_allowlist_is_off(client, monkeypatch):
    monkeypatch.setattr(settings, "target_allowlist_enabled", False)
    _, h = await auth(client)
    assert (await client.get("/config", headers=h)).json()["allow_custom_target"] is True


async def test_runs_are_flagged_demo_unless_owned(client):
    code_id, h = await auth(client, "demo-flag")
    own = await make_run(code_id)
    demo = await make_run(None)
    items = (await client.get("/benchmark/runs", headers=h)).json()["items"]
    flags = {}
    for item in items:
        flags[item["id"]] = item["is_demo"]
    assert flags[str(own)] is False
    assert flags[str(demo)] is True


async def test_nothing_is_demo_when_auth_is_off(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", False)
    await make_run(None)
    items = (await client.get("/benchmark/runs")).json()["items"]
    assert items[0]["is_demo"] is False


async def test_caller_can_clear_their_own_baseline(client):
    code_id, h = await auth(client, "clear-own")
    run = await make_run(code_id, baseline=True)
    demo = await make_run(None, baseline=True)

    assert (await client.delete("/benchmark/runs/baseline", headers=h)).status_code == 200
    # Own baseline is gone, so the demo baseline applies again.
    baseline = (await client.get("/benchmark/runs/baseline", headers=h)).json()
    assert baseline["id"] == str(demo)
    assert baseline["id"] != str(run)


async def test_clearing_never_touches_the_demo_baseline(client):
    _, h = await auth(client, "clear-demo")
    demo = await make_run(None, baseline=True)
    # Nothing of their own to clear: 404, and the demo baseline stays.
    assert (await client.delete("/benchmark/runs/baseline", headers=h)).status_code == 404
    assert (await client.get("/benchmark/runs/baseline", headers=h)).json()["id"] == str(demo)


async def test_clear_baseline_requires_a_session(client):
    assert (await client.delete("/benchmark/runs/baseline")).status_code == 401


async def test_retry_after_is_exposed_to_browsers(client):
    resp = await client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert "retry-after" in resp.headers.get("access-control-expose-headers", "").lower()
