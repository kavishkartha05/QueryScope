import os
import socket
import tempfile

# Test configuration must be in the environment BEFORE app modules import,
# because app.main builds the app (and validates secrets) at import time.
# These are throwaway test values, not real credentials.
_DB_FILE = os.path.join(tempfile.mkdtemp(prefix="queryscope-test-"), "test.db")
# TEST_DATABASE_URL lets CI or a developer run the suite against real Postgres.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", f"sqlite+aiosqlite:///{_DB_FILE}")
os.environ["AUTH_ENABLED"] = "true"
os.environ["SESSION_SECRET"] = "test-session-secret-0123456789abcdef0123456789"
os.environ["CODE_PEPPER"] = "test-code-pepper-0123456789abcdef0123456789abc"
os.environ["ADMIN_API_KEY"] = "test-admin-key-0123456789abcdef"
os.environ["AZURE_SEARCH_ENDPOINT"] = ""
os.environ["AZURE_SEARCH_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""

import uuid  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.db import AsyncSessionLocal, Base, engine  # noqa: E402
from app.core.security import generate_code, hash_code, login_limiter  # noqa: E402
from app.main import app  # noqa: E402
from app.models.access_code import AccessCode  # noqa: E402
from app.models.run import Metrics, Run, RunStatus  # noqa: E402

ADMIN = {"X-Admin-Key": os.environ["ADMIN_API_KEY"]}


@pytest.fixture(autouse=True)
def _isolate_settings_and_limiter(monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", True)
    monkeypatch.setattr(settings, "session_secret", os.environ["SESSION_SECRET"])
    monkeypatch.setattr(settings, "code_pepper", os.environ["CODE_PEPPER"])
    monkeypatch.setattr(settings, "admin_api_key", os.environ["ADMIN_API_KEY"])
    monkeypatch.setattr(settings, "trusted_proxy_hops", 0)
    # Never reach Azure/OpenAI from tests.
    async def _no_index(**kwargs):
        return None

    monkeypatch.setattr("app.api.runs.index_run", _no_index)
    login_limiter._per_ip.clear()
    login_limiter._global.clear()


# Public-looking addresses for tests that need a target to resolve.
DEFAULT_DNS = {
    "httpbin.org": ["93.184.216.34"],
    "example.com": ["93.184.216.34"],
}


class FakeDNS:
    """hostname -> addresses table; `calls` records every lookup made."""

    def __init__(self) -> None:
        self.table: dict[str, list[str]] = dict(DEFAULT_DNS)
        self.calls: list[str] = []

    def __setitem__(self, host: str, addresses: list[str]) -> None:
        self.table[host] = addresses

    async def resolve(self, host: str, port: int) -> list[str]:
        self.calls.append(host)
        if host not in self.table:
            raise socket.gaierror("name not known")
        return list(self.table[host])


@pytest.fixture(autouse=True)
def dns(monkeypatch):
    """
    Replace real DNS so tests never touch the network and can make any name
    resolve to any address. Unknown names fail to resolve, like NXDOMAIN.
    """
    fake = FakeDNS()
    monkeypatch.setattr("app.services.ssrf._resolve_host", fake.resolve)
    return fake


@pytest_asyncio.fixture(autouse=True)
async def _fresh_schema():
    # Each test runs on its own event loop; pooled asyncpg connections are bound
    # to the loop that opened them, so drop the pool before and after every test.
    await engine.dispose()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def make_code(label: str, revoked: bool = False) -> tuple[uuid.UUID, str]:
    """Insert an access code; return (id, plaintext code)."""
    code_value = generate_code(label)
    row = AccessCode(label=label, code_hash=hash_code(code_value))
    if revoked:
        row.revoked_at = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        session.add(row)
        await session.commit()
        return row.id, code_value


async def login(client: httpx.AsyncClient, code_value: str) -> dict:
    resp = await client.post("/auth/login", json={"code": code_value})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


async def make_run(
    owner: uuid.UUID | None,
    *,
    p50: float = 100.0,
    baseline: bool = False,
    age_minutes: int = 0,
    status: RunStatus = RunStatus.done,
    num_requests: int = 10,
    created_at: datetime | None = None,
) -> uuid.UUID:
    run = Run(
        target_url="https://httpbin.org/get",
        method="GET",
        num_requests=num_requests,
        concurrency=2,
        status=status,
        is_baseline=baseline,
        access_code_id=owner,
        created_at=created_at or (datetime.now(timezone.utc) - timedelta(minutes=age_minutes)),
    )
    async with AsyncSessionLocal() as session:
        session.add(run)
        await session.flush()
        session.add(
            Metrics(
                run_id=run.id,
                latencies=[p50] * 10,
                p50=p50,
                p95=p50 * 1.5,
                p99=p50 * 2,
                throughput=10.0,
                error_rate=0.0,
            )
        )
        await session.commit()
        return run.id
