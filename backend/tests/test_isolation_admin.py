import uuid
from sqlalchemy import select

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.models.run import Run
from app.services.scope import search_filter
from tests.conftest import ADMIN, login, make_code, make_run


async def two_recruiters(client):
    a_id, a_code = await make_code("alpha-recruiter")
    b_id, b_code = await make_code("bravo-recruiter")
    return (a_id, await login(client, a_code)), (b_id, await login(client, b_code))


async def ids(client, headers):
    resp = await client.get("/benchmark/runs", headers=headers)
    assert resp.status_code == 200
    return {item["id"] for item in resp.json()["items"]}, resp.json()


async def test_list_shows_own_plus_demo_only(client):
    (a_id, a_h), (b_id, b_h) = await two_recruiters(client)
    own_a = await make_run(a_id)
    own_b = await make_run(b_id)
    demo = await make_run(None)

    seen_a, body_a = await ids(client, a_h)
    seen_b, _ = await ids(client, b_h)
    assert seen_a == {str(own_a), str(demo)}
    assert seen_b == {str(own_b), str(demo)}
    assert body_a["total"] == 2


async def test_other_recruiters_run_is_404_everywhere(client):
    (a_id, a_h), (b_id, b_h) = await two_recruiters(client)
    b_run = await make_run(b_id)
    for path in (f"/benchmark/runs/{b_run}", f"/benchmark/runs/{b_run}/metrics"):
        assert (await client.get(path, headers=a_h)).status_code == 404
        assert (await client.get(path, headers=b_h)).status_code == 200
    assert (await client.patch(f"/benchmark/runs/{b_run}/baseline", headers=a_h)).status_code == 404


async def test_demo_runs_readable_but_not_modifiable(client):
    (a_id, a_h), _ = await two_recruiters(client)
    demo = await make_run(None)
    assert (await client.get(f"/benchmark/runs/{demo}", headers=a_h)).status_code == 200
    assert (await client.get(f"/benchmark/runs/{demo}/metrics", headers=a_h)).status_code == 200
    assert (await client.patch(f"/benchmark/runs/{demo}/baseline", headers=a_h)).status_code == 403


async def test_baseline_is_per_code_with_demo_fallback(client):
    (a_id, a_h), (b_id, b_h) = await two_recruiters(client)
    demo_base = await make_run(None, p50=100.0, baseline=True)
    a1 = await make_run(a_id, p50=200.0, age_minutes=2)
    a2 = await make_run(a_id, p50=300.0, age_minutes=1)

    # No own baseline: falls back to the demo baseline.
    resp = await client.get("/benchmark/runs/baseline", headers=a_h)
    assert resp.status_code == 200 and resp.json()["id"] == str(demo_base)
    _, body = await ids(client, a_h)
    by_id = {item["id"]: item for item in body["items"]}
    assert by_id[str(demo_base)]["is_baseline"] is True
    assert by_id[str(a1)]["delta_p50_pct"] == 100.0

    # A pins their own baseline; the demo baseline stops being flagged for A.
    pin = await client.patch(f"/benchmark/runs/{a1}/baseline", headers=a_h)
    assert pin.status_code == 200 and pin.json()["is_baseline"] is True
    resp = await client.get("/benchmark/runs/baseline", headers=a_h)
    assert resp.json()["id"] == str(a1)
    _, body = await ids(client, a_h)
    by_id = {item["id"]: item for item in body["items"]}
    assert by_id[str(a1)]["is_baseline"] is True
    assert by_id[str(demo_base)]["is_baseline"] is False
    assert by_id[str(a2)]["delta_p50_pct"] == 50.0

    # Moving the baseline within A clears the old one.
    assert (await client.patch(f"/benchmark/runs/{a2}/baseline", headers=a_h)).status_code == 200
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(Run).where(Run.access_code_id == a_id))).scalars().all()
        flags = []
        for r in rows:
            flags.append(r.is_baseline)
        assert sorted(flags) == [False, True]

    # B is unaffected and still sees the demo baseline.
    resp = await client.get("/benchmark/runs/baseline", headers=b_h)
    assert resp.json()["id"] == str(demo_base)
    # Pinning again is a 400.
    assert (await client.patch(f"/benchmark/runs/{a2}/baseline", headers=a_h)).status_code == 400


async def test_baseline_404_when_none_anywhere(client):
    (a_id, a_h), _ = await two_recruiters(client)
    assert (await client.get("/benchmark/runs/baseline", headers=a_h)).status_code == 404


async def test_create_run_is_tagged_with_the_code(client, monkeypatch):
    (a_id, a_h), _ = await two_recruiters(client)

    async def _noop(run_id, req):
        return None

    monkeypatch.setattr("app.api.runs._execute_and_persist", _noop)
    resp = await client.post(
        "/benchmark", headers=a_h,
        json={"target_url": "https://httpbin.org/get", "method": "GET",
              "num_requests": 5, "concurrency": 2},
    )
    assert resp.status_code == 202
    async with AsyncSessionLocal() as session:
        run = await session.get(Run, uuid.UUID(resp.json()["run_id"]))
        assert run.access_code_id == a_id


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

async def test_admin_routes_require_the_admin_key(client):
    (a_id, a_h), _ = await two_recruiters(client)
    run = await make_run(a_id)
    calls = [
        ("GET", "/admin/codes"),
        ("POST", "/admin/codes"),
        ("POST", f"/admin/codes/{a_id}/revoke"),
        ("PATCH", f"/admin/runs/{run}/baseline"),
        ("DELETE", "/benchmark/runs"),
    ]
    for method, path in calls:
        kwargs = {"json": {"label": "new-label"}} if method == "POST" and path == "/admin/codes" else {}
        assert (await client.request(method, path, **kwargs)).status_code in (401, 403), path
        # A valid recruiter token is NOT admin.
        assert (await client.request(method, path, headers=a_h, **kwargs)).status_code in (401, 403), path
        wrong = {"X-Admin-Key": "wrong-key-wrong-key-wrong-key-1234"}
        assert (await client.request(method, path, headers=wrong, **kwargs)).status_code == 403, path


async def test_admin_disabled_when_key_unset(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "")
    assert (await client.get("/admin/codes", headers={"X-Admin-Key": ""})).status_code == 403
    assert (await client.get("/admin/codes")).status_code == 403


async def test_admin_create_list_revoke_flow(client):
    created = await client.post("/admin/codes", headers=ADMIN, json={"label": "stripe-rebecca"})
    assert created.status_code == 201
    body = created.json()
    assert body["code"].startswith("stripe-rebecca.")

    # The returned code works, the stored value is a hash (not the code).
    token_headers = await login(client, body["code"])
    async with AsyncSessionLocal() as session:
        from app.models.access_code import AccessCode
        row = await session.get(AccessCode, uuid.UUID(body["id"]))
        assert body["code"] not in row.code_hash and len(row.code_hash) == 64

    dup = await client.post("/admin/codes", headers=ADMIN, json={"label": "stripe-rebecca"})
    assert dup.status_code == 409
    bad = await client.post("/admin/codes", headers=ADMIN, json={"label": "Bad Label!"})
    assert bad.status_code == 422

    await make_run(uuid.UUID(body["id"]))
    await make_run(uuid.UUID(body["id"]))
    listing = await client.get("/admin/codes", headers=ADMIN)
    assert listing.status_code == 200
    item = listing.json()[0]
    assert item["label"] == "stripe-rebecca"
    assert item["run_count"] == 2
    assert item["last_used_at"] is not None and item["revoked_at"] is None
    assert "code" not in item and "code_hash" not in item

    revoked = await client.post(f"/admin/codes/{body['id']}/revoke", headers=ADMIN)
    assert revoked.status_code == 200 and revoked.json()["revoked_at"] is not None
    first_time = revoked.json()["revoked_at"]
    again = await client.post(f"/admin/codes/{body['id']}/revoke", headers=ADMIN)
    assert again.json()["revoked_at"] == first_time
    assert (await client.get("/benchmark/runs", headers=token_headers)).status_code == 401
    missing = await client.post(f"/admin/codes/{uuid.uuid4()}/revoke", headers=ADMIN)
    assert missing.status_code == 404


async def test_admin_sets_demo_baseline_only_on_demo_runs(client):
    (a_id, a_h), _ = await two_recruiters(client)
    d1 = await make_run(None, baseline=True)
    d2 = await make_run(None)
    owned = await make_run(a_id)
    assert (await client.patch(f"/admin/runs/{owned}/baseline", headers=ADMIN)).status_code == 404
    ok = await client.patch(f"/admin/runs/{d2}/baseline", headers=ADMIN)
    assert ok.status_code == 200 and ok.json()["is_baseline"] is True
    resp = await client.get("/benchmark/runs/baseline", headers=a_h)
    assert resp.json()["id"] == str(d2)
    assert str(d1) != resp.json()["id"]


async def test_delete_keeps_demo_runs_by_default(client):
    (a_id, a_h), _ = await two_recruiters(client)
    own = await make_run(a_id)
    demo = await make_run(None)
    assert (await client.delete("/benchmark/runs", headers=ADMIN)).status_code == 200
    async with AsyncSessionLocal() as session:
        assert await session.get(Run, own) is None
        assert await session.get(Run, demo) is not None
    assert (await client.delete("/benchmark/runs?include_demo=true", headers=ADMIN)).status_code == 200
    async with AsyncSessionLocal() as session:
        assert await session.get(Run, demo) is None


async def test_delete_with_auth_disabled_wipes_everything_like_before(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", False)
    demo = await make_run(None)
    assert (await client.delete("/benchmark/runs")).status_code == 200
    async with AsyncSessionLocal() as session:
        assert await session.get(Run, demo) is None


# ---------------------------------------------------------------------------
# Diagnose scoping
# ---------------------------------------------------------------------------

def test_search_filter_shape():
    code = uuid.UUID("11111111-1111-1111-1111-111111111111")
    assert search_filter(code) == (
        "access_code_id eq '11111111-1111-1111-1111-111111111111' "
        "or access_code_id eq 'demo' or access_code_id eq null"
    )
    assert search_filter(None) == "access_code_id eq 'demo' or access_code_id eq null"


async def test_recent_runs_context_is_scoped(client):
    from app.services.rca import _fetch_recent_runs_context

    (a_id, _), (b_id, _) = await two_recruiters(client)
    mine = await make_run(a_id, p50=111.0)
    theirs = await make_run(b_id, p50=222.0)
    demo = await make_run(None, p50=333.0)
    async with AsyncSessionLocal() as session:
        text = await _fetch_recent_runs_context(session, a_id)
    assert str(mine) in text and str(demo) in text
    assert str(theirs) not in text


async def test_diagnose_passes_owner_filter_into_the_vector_query(client, monkeypatch):
    """The OData filter must reach the retriever (in-query), not be applied after top-k."""
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    from llama_index.core.embeddings import MockEmbedding

    import app.services.rca as rca

    captured = {}

    class FakeRetriever:
        def retrieve(self, question):
            return []

    class FakeIndex:
        def as_retriever(self, **kwargs):
            captured.update(kwargs)
            return FakeRetriever()

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def close(self):
            return None

    class FakeAsyncClient(FakeClient):
        async def close(self):
            return None

    def fake_store(**kwargs):
        captured["store_kwargs"] = kwargs
        return object()

    monkeypatch.setattr(rca, "SyncSearchIndexClient", FakeClient)
    monkeypatch.setattr(rca, "AsyncSearchIndexClient", FakeAsyncClient)
    monkeypatch.setattr(rca, "AzureAISearchVectorStore", fake_store)
    monkeypatch.setattr(rca.StorageContext, "from_defaults", staticmethod(lambda **kw: object()))
    monkeypatch.setattr(rca.VectorStoreIndex, "from_vector_store", staticmethod(lambda **kw: FakeIndex()))
    monkeypatch.setattr(rca, "OpenAIEmbedding", lambda **kw: MockEmbedding(embed_dim=8))
    monkeypatch.setattr(rca, "ChatOpenAI", lambda **kw: FakeListChatModel(responses=["diagnosis text"]))

    (a_id, a_h), _ = await two_recruiters(client)
    resp = await client.post("/benchmark/diagnose", headers=a_h, json={"question": "why slow?"})
    assert resp.status_code == 200 and resp.json()["diagnosis"] == "diagnosis text"
    assert captured["vector_store_kwargs"]["odata_filter"] == search_filter(a_id)
    assert captured["similarity_top_k"] == 5
    assert captured["store_kwargs"]["filterable_metadata_field_keys"] == ["access_code_id"]
