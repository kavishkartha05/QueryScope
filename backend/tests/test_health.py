import asyncio

from sqlalchemy.exc import OperationalError

from app.core.config import settings


async def test_healthy_database_returns_200(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "ok"}


async def test_health_needs_no_credentials(client):
    assert (await client.get("/health")).status_code == 200


async def test_database_error_returns_503_without_details(client, monkeypatch):
    async def _down():
        raise OperationalError("SELECT 1", {}, Exception("connection refused to db.internal:5432"))

    monkeypatch.setattr("app.main._probe_database", _down)
    resp = await client.get("/health")
    assert resp.status_code == 503
    assert resp.json() == {"status": "unavailable", "database": "down"}
    assert "internal" not in resp.text and "5432" not in resp.text


async def test_hanging_database_returns_503_within_the_timeout(client, monkeypatch):
    async def _hang():
        await asyncio.sleep(30)

    monkeypatch.setattr("app.main._probe_database", _hang)
    monkeypatch.setattr(settings, "health_db_timeout_s", 0.1)
    loop = asyncio.get_running_loop()
    began = loop.time()
    resp = await client.get("/health")
    assert resp.status_code == 503
    assert loop.time() - began < 3


async def test_it_really_queries_the_database(client, monkeypatch):
    """The probe goes through the engine: a broken engine means 503."""
    class _Broken:
        def connect(self):
            raise OperationalError("connect", {}, Exception("no route"))

    monkeypatch.setattr("app.main.engine", _Broken())
    assert (await client.get("/health")).status_code == 503
