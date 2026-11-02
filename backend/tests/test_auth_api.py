import jwt
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.models.access_code import AccessCode
from tests.conftest import login, make_code

PROTECTED = [
    ("GET", "/benchmark/runs"),
    ("GET", "/benchmark/runs/baseline"),
    ("POST", "/benchmark"),
    ("POST", "/benchmark/llm"),
    ("POST", "/benchmark/diagnose"),
    ("PATCH", "/benchmark/runs/00000000-0000-0000-0000-000000000001/baseline"),
    ("GET", "/benchmark/runs/00000000-0000-0000-0000-000000000001"),
    ("GET", "/benchmark/runs/00000000-0000-0000-0000-000000000001/metrics"),
]


async def test_health_is_open(client):
    resp = await client.get("/health")
    assert resp.status_code == 200


async def test_protected_routes_reject_missing_and_bad_tokens(client):
    for method, path in PROTECTED:
        resp = await client.request(method, path)
        assert resp.status_code == 401, (method, path)
        resp = await client.request(method, path, headers={"Authorization": "Bearer nope"})
        assert resp.status_code == 401, (method, path)
        resp = await client.request(method, path, headers={"Authorization": "Basic abc"})
        assert resp.status_code == 401, (method, path)


async def test_login_success_returns_working_token(client):
    _, code = await make_code("stripe-rebecca")
    resp = await client.post("/auth/login", json={"code": code})
    assert resp.status_code == 200
    body = resp.json()
    assert body["label"] == "stripe-rebecca"
    assert body["token_type"] == "bearer"
    runs = await client.get("/benchmark/runs", headers={"Authorization": f"Bearer {body['token']}"})
    assert runs.status_code == 200

    # last_used_at was recorded.
    async with AsyncSessionLocal() as session:
        row = (await session.execute(select(AccessCode))).scalars().one()
        assert row.last_used_at is not None


async def test_login_failures_are_indistinguishable(client):
    _, revoked_code = await make_code("old-recruiter", revoked=True)
    await make_code("real-recruiter")
    bodies = []
    for submitted in ["totally-unknown.AAAAAAAAAA", revoked_code, "x", "real-recruiter.WRONGWRONG"]:
        resp = await client.post("/auth/login", json={"code": submitted})
        assert resp.status_code == 401
        bodies.append(resp.json())
    assert all(b == bodies[0] for b in bodies)


async def test_login_validation_rejects_empty_and_oversized(client):
    assert (await client.post("/auth/login", json={"code": ""})).status_code == 422
    assert (await client.post("/auth/login", json={"code": "a" * 500})).status_code == 422


async def test_login_is_throttled_per_ip_then_recovers_on_success_elsewhere(client, monkeypatch):
    monkeypatch.setattr(settings, "login_max_failures_per_ip", 3)
    _, code = await make_code("real-recruiter")
    for _ in range(3):
        assert (await client.post("/auth/login", json={"code": "bad.guess0000"})).status_code == 401
    blocked = await client.post("/auth/login", json={"code": "bad.guess0000"})
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    # Even the CORRECT code is refused while blocked, so guessing gets no signal.
    assert (await client.post("/auth/login", json={"code": code})).status_code == 429


async def test_global_throttle_applies_across_ips(client, monkeypatch):
    monkeypatch.setattr(settings, "login_max_failures_global", 3)
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    for i in range(3):
        resp = await client.post(
            "/auth/login", json={"code": "bad.guess0000"},
            headers={"X-Forwarded-For": f"203.0.113.{i}"},
        )
        assert resp.status_code == 401
    resp = await client.post(
        "/auth/login", json={"code": "bad.guess0000"},
        headers={"X-Forwarded-For": "198.51.100.77"},
    )
    assert resp.status_code == 429


async def test_spoofed_forwarded_header_does_not_evade_per_ip_limit(client, monkeypatch):
    # No trusted proxy configured: rotating X-Forwarded-For must not help.
    monkeypatch.setattr(settings, "login_max_failures_per_ip", 2)
    for i in range(2):
        await client.post("/auth/login", json={"code": "bad.guess0000"},
                          headers={"X-Forwarded-For": f"203.0.113.{i}"})
    resp = await client.post("/auth/login", json={"code": "bad.guess0000"},
                             headers={"X-Forwarded-For": "198.51.100.5"})
    assert resp.status_code == 429


async def test_revoking_a_code_kills_live_tokens_immediately(client):
    code_id, code = await make_code("stripe-rebecca")
    headers = await login(client, code)
    assert (await client.get("/benchmark/runs", headers=headers)).status_code == 200

    async with AsyncSessionLocal() as session:
        row = await session.get(AccessCode, code_id)
        row.revoked_at = datetime.now(timezone.utc)
        await session.commit()

    assert (await client.get("/benchmark/runs", headers=headers)).status_code == 401
    assert (await client.post("/auth/login", json={"code": code})).status_code == 401


async def test_expired_and_forged_tokens_rejected(client):
    code_id, _ = await make_code("stripe-rebecca")
    now = datetime.now(timezone.utc)
    claims = {"iss": "queryscope", "sub": str(code_id), "iat": int(now.timestamp()),
              "exp": int((now - timedelta(seconds=5)).timestamp())}
    expired = jwt.encode(claims, settings.session_secret, algorithm="HS256")
    forged = jwt.encode({**claims, "exp": int((now + timedelta(hours=1)).timestamp())},
                        "y" * 40, algorithm="HS256")
    for token in (expired, forged):
        resp = await client.get("/benchmark/runs", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401


async def test_valid_signature_for_unknown_code_id_rejected(client):
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {"iss": "queryscope", "sub": "22222222-2222-2222-2222-222222222222",
         "iat": int(now.timestamp()), "exp": int((now + timedelta(hours=1)).timestamp())},
        settings.session_secret, algorithm="HS256",
    )
    resp = await client.get("/benchmark/runs", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


async def test_auth_disabled_opens_routes_and_login_404(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", False)
    assert (await client.get("/benchmark/runs")).status_code == 200
    assert (await client.post("/auth/login", json={"code": "x"})).status_code == 404
