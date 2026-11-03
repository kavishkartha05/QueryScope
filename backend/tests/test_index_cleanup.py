import pathlib
import uuid

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.models.run import Run
from app.services import indexer
from tests.conftest import ADMIN, login, make_code, make_run

RUN_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
RUN_B = uuid.UUID("22222222-2222-2222-2222-222222222222")


class _Result:
    def __init__(self, succeeded=True):
        self.succeeded = succeeded


class _Pager:
    def __init__(self, items):
        self._items = items

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for item in self._items:
            yield item


class FakeIndex:
    """Just enough of azure.search.documents.aio.SearchClient."""

    def __init__(self, docs):
        self.docs = docs  # key -> {"doc_id":..., "content":...}
        self.deleted: list[str] = []
        self.closed = False
        self.fail_delete = False
        self.queries: list[dict] = []

    async def search(self, search_text, filter=None, select=None, top=None, search_fields=None):
        self.queries.append({"text": search_text, "filter": filter, "fields": search_fields})
        items = []
        for key, doc in self.docs.items():
            if filter is not None:
                wanted = filter.split("'")[1]
                if doc["doc_id"] == wanted:
                    items.append({"id": key})
            else:
                # Fuzzy text search: returns anything sharing a token with the phrase.
                token = search_text.strip('"').split("-")[0]
                if token in doc["content"]:
                    items.append({"id": key, "content": doc["content"]})
        return _Pager(items)

    async def delete_documents(self, documents):
        results = []
        for document in documents:
            if self.fail_delete:
                results.append(_Result(False))
            else:
                self.deleted.append(document["id"])
                self.docs.pop(document["id"], None)
                results.append(_Result(True))
        return results

    async def close(self):
        self.closed = True


@pytest.fixture
def azure_on(monkeypatch):
    monkeypatch.setattr(settings, "azure_search_endpoint", "https://search.example.test")
    monkeypatch.setattr(settings, "azure_search_key", "test-key-not-real")


def install(monkeypatch, fake):
    monkeypatch.setattr(indexer, "_search_client", lambda: fake)


async def test_documents_are_found_by_doc_id_and_deleted(azure_on, monkeypatch):
    fake = FakeIndex({
        "k1": {"doc_id": str(RUN_A), "content": f"Benchmark run {RUN_A} against x"},
        "k2": {"doc_id": str(RUN_B), "content": f"Benchmark run {RUN_B} against y"},
    })
    install(monkeypatch, fake)
    assert await indexer.delete_run_documents([RUN_A]) == 1
    assert fake.deleted == ["k1"]
    assert "k2" in fake.docs
    assert fake.closed is True


async def test_old_documents_with_a_random_doc_id_are_found_by_their_text(azure_on, monkeypatch):
    fake = FakeIndex({
        "old": {"doc_id": "some-random-uuid", "content": f"Benchmark run {RUN_A} against x"},
        # Shares the first token (so the fuzzy search returns it) but is another run.
        "other": {"doc_id": "another-random", "content": f"Benchmark run {uuid.UUID('11111111-9999-9999-9999-999999999999')} against z"},
    })
    install(monkeypatch, fake)
    assert await indexer.delete_run_documents([RUN_A]) == 1
    assert fake.deleted == ["old"]
    assert "other" in fake.docs   # a fuzzy hit is not deleted unless the full id is in its text


async def test_a_run_with_no_documents_is_fine(azure_on, monkeypatch):
    install(monkeypatch, FakeIndex({}))
    assert await indexer.delete_run_documents([RUN_A, RUN_B]) == 0


async def test_failure_to_delete_raises(azure_on, monkeypatch):
    fake = FakeIndex({"k1": {"doc_id": str(RUN_A), "content": str(RUN_A)}})
    fake.fail_delete = True
    install(monkeypatch, fake)
    with pytest.raises(RuntimeError):
        await indexer.delete_run_documents([RUN_A])
    assert fake.closed is True


async def test_nothing_happens_when_azure_is_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "azure_search_endpoint", "")
    monkeypatch.setattr(settings, "azure_search_key", "")

    def _boom():
        raise AssertionError("must not create a client")

    monkeypatch.setattr(indexer, "_search_client", _boom)
    assert await indexer.delete_run_documents([RUN_A]) == 0


async def test_filter_uses_only_a_uuid_string(azure_on, monkeypatch):
    fake = FakeIndex({})
    install(monkeypatch, fake)
    await indexer.delete_run_documents([RUN_A])
    assert fake.queries[0]["filter"] == f"doc_id eq '{RUN_A}'"


def test_index_run_uses_the_run_id_as_the_document_id():
    from llama_index.core import Document

    doc = Document(text="t", id_=str(RUN_A), metadata={"run_id": str(RUN_A)})
    assert doc.doc_id == str(RUN_A)
    source = pathlib.Path(indexer.__file__).read_text()
    assert "id_=str(run_id)" in source


# --- through the API -----------------------------------------------------------

async def run_ids() -> set:
    async with AsyncSessionLocal() as session:
        return set((await session.execute(select(Run.id))).scalars().all())


async def test_reset_deletes_index_documents_for_exactly_the_deleted_runs(client, monkeypatch):
    a_id, _ = await make_code("alpha-recruiter")
    own1, own2 = await make_run(a_id), await make_run(a_id)
    demo = await make_run(None)
    seen = []

    async def _record(ids):
        seen.append(set(ids))
        return len(ids)

    monkeypatch.setattr("app.api.runs.delete_run_documents", _record)
    resp = await client.delete("/benchmark/runs", headers=ADMIN)
    assert resp.status_code == 200
    # Default on a hosted deployment keeps the demo runs, so their documents stay too.
    assert seen == [{own1, own2}]
    assert await run_ids() == {demo}

    seen.clear()
    resp = await client.delete("/benchmark/runs?include_demo=true", headers=ADMIN)
    assert resp.status_code == 200
    assert seen == [{demo}]
    assert await run_ids() == set()


async def test_reset_keeps_the_runs_if_the_index_cannot_be_cleaned(client, monkeypatch):
    a_id, _ = await make_code("alpha-recruiter")
    own = await make_run(a_id)

    async def _fail(ids):
        raise RuntimeError("azure unavailable")

    monkeypatch.setattr("app.api.runs.delete_run_documents", _fail)
    resp = await client.delete("/benchmark/runs", headers=ADMIN)
    assert resp.status_code == 502
    assert "no runs were deleted" in resp.json()["detail"]
    assert "azure unavailable" not in resp.text
    assert await run_ids() == {own}


async def test_reset_with_nothing_to_delete_succeeds(client, monkeypatch):
    called = []

    async def _record(ids):
        called.append(ids)
        return 0

    monkeypatch.setattr("app.api.runs.delete_run_documents", _record)
    assert (await client.delete("/benchmark/runs", headers=ADMIN)).status_code == 200
    assert called == [[]]


async def test_metrics_are_still_removed_with_their_runs(client, monkeypatch):
    from app.core.db import engine
    from app.models.run import Metrics

    if engine.dialect.name == "sqlite":
        pytest.skip("SQLite ignores ON DELETE CASCADE unless PRAGMA foreign_keys is on")
    a_id, _ = await make_code("alpha-recruiter")
    await make_run(a_id)

    async def _ok(ids):
        return 0

    monkeypatch.setattr("app.api.runs.delete_run_documents", _ok)
    await client.delete("/benchmark/runs", headers=ADMIN)
    async with AsyncSessionLocal() as session:
        count = (await session.execute(select(func.count()).select_from(Metrics))).scalar_one()
    assert count == 0
