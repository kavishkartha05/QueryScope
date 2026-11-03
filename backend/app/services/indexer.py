import logging
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

from azure.core.credentials import AzureKeyCredential
from azure.search.documents.indexes import SearchIndexClient as SyncSearchIndexClient
from azure.search.documents.indexes.aio import SearchIndexClient as AsyncSearchIndexClient
from llama_index.core import Document, StorageContext, VectorStoreIndex
from llama_index.core.settings import Settings as LlamaSettings
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.vector_stores.azureaisearch import AzureAISearchVectorStore, IndexManagement

from app.core.config import settings


async def index_run(
    run_id: uuid.UUID,
    target_url: str,
    method: str,
    num_requests: int,
    p50: float,
    p95: float,
    p99: float,
    throughput: float,
    error_rate: float,
    created_at: datetime,
    access_code_id: str = "demo",
) -> None:
    """
    Embed a plain-text run summary and persist it to Azure AI Search.

    Called after a benchmark completes so the RCA query pipeline can retrieve
    relevant historical runs via semantic similarity.
    """
    logger.info("index_run called for run_id=%s", run_id)

    # Plain-text format is intentional: embedding a structured JSON blob would
    # dilute the semantic signal that the embedding model extracts. Natural
    # language sentences produce richer, more comparable vector representations.
    summary = (
        f"Benchmark run {run_id} against {target_url} ({method}) "
        f"with {num_requests} requests. "
        f"p50={p50:.2f}ms p95={p95:.2f}ms p99={p99:.2f}ms "
        f"throughput={throughput:.2f}req/s error_rate={error_rate:.4f} "
        f"recorded at {created_at.isoformat()}."
    )

    # Store run_id in metadata so the RCA chain can look up the full DB row
    # after retrieval without embedding that data in the document text.
    # access_code_id is the owner ("demo" or a code UUID). It is also a
    # filterable index field (see filterable_metadata_field_keys below) so
    # diagnose can restrict retrieval to own-or-demo runs inside the query.
    # id_ is the run id so the stored doc_id field equals it; that is what lets
    # delete_run_documents find (and remove) this run's document later.
    doc = Document(
        text=summary,
        id_=str(run_id),
        metadata={"run_id": str(run_id), "access_code_id": access_code_id},
    )

    # Configure the embedding model globally for this LlamaIndex call.
    # text-embedding-3-small balances cost and quality for short run summaries;
    # the 1536-dim output matches Azure AI Search's default vector config.
    LlamaSettings.embed_model = OpenAIEmbedding(
        model="text-embedding-3-small",
        api_key=settings.openai_api_key,
    )

    credential = AzureKeyCredential(settings.azure_search_key)

    # AzureAISearchVectorStore requires both clients: the sync one is used for
    # index management operations (VALIDATE_INDEX introspection), while the
    # async one is used for document upserts so we don't block the event loop.
    sync_index_client = SyncSearchIndexClient(
        endpoint=settings.azure_search_endpoint,
        credential=credential,
    )
    async_index_client = AsyncSearchIndexClient(
        endpoint=settings.azure_search_endpoint,
        credential=credential,
    )

    try:
        # AzureAISearchVectorStore is the only vector store in this project
        # (see CLAUDE.md, no alternatives). IndexManagement.VALIDATE_INDEX
        # asserts the index exists rather than trying to create it at runtime,
        # which keeps IAM requirements minimal (no index-write permissions needed).
        vector_store = AzureAISearchVectorStore(
            search_or_index_client=sync_index_client,
            async_search_or_index_client=async_index_client,
            index_name=settings.azure_search_index,
            index_management=IndexManagement.VALIDATE_INDEX,
            id_field_key="id",
            chunk_field_key="content",
            embedding_field_key="content_vector",
            metadata_string_field_key="metadata",
            doc_id_field_key="doc_id",
            filterable_metadata_field_keys=["access_code_id"],
        )

        logger.info("Indexing run %s to Azure AI Search", run_id)

        # from_documents embeds the document and upserts it into the vector store
        # in one call. We don't need a persistent StorageContext on disk because
        # Azure AI Search is the durable store.
        # afrom_documents does not exist in llama-index-core 0.14.x, sync only.
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        VectorStoreIndex.from_documents(
            [doc],
            storage_context=storage_context,
            show_progress=False,
        )

        logger.info("Successfully indexed run %s", run_id)
    finally:
        await async_index_client.close()
        sync_index_client.close()


# ---------------------------------------------------------------------------
# Deleting documents
# ---------------------------------------------------------------------------

def _search_client():
    """Async client for the configured index. A function so tests can replace it."""
    from azure.search.documents.aio import SearchClient

    return SearchClient(
        endpoint=settings.azure_search_endpoint,
        index_name=settings.azure_search_index,  # the index name comes only from config
        credential=AzureKeyCredential(settings.azure_search_key),
    )


async def _find_document_ids(client, run_id: uuid.UUID) -> list[str]:
    """Index keys of every document that belongs to this run."""
    run_text = str(run_id)  # a UUID prints as hex and hyphens: safe inside an OData string
    found: list[str] = []

    # Documents indexed by this version have doc_id == run id (exact, filterable).
    results = await client.search(
        search_text="*", filter=f"doc_id eq '{run_text}'", select=["id"], top=1000
    )
    async for item in results:
        if item["id"] not in found:
            found.append(item["id"])

    # Documents indexed before that change have a random doc_id, but their text
    # starts "Benchmark run <id> against ...". Find them by phrase and confirm the
    # id really is in the text before deleting, so a fuzzy match never deletes
    # another run's document.
    results = await client.search(
        search_text=f'"{run_text}"', search_fields=["content"], select=["id", "content"], top=50
    )
    async for item in results:
        if run_text in (item.get("content") or "") and item["id"] not in found:
            found.append(item["id"])
    return found


async def delete_run_documents(run_ids: list[uuid.UUID]) -> int:
    """
    Remove the search documents of the given runs, so deleting runs leaves no
    orphans behind. Returns how many documents were deleted. Raises if Azure
    reports a failure, so the caller can keep the database rows and retry.
    Does nothing when Azure Search is not configured (local development).
    """
    if not run_ids:
        return 0
    if not settings.azure_search_endpoint or not settings.azure_search_key:
        logger.info("Azure Search not configured; no index documents to delete")
        return 0

    client = _search_client()
    deleted = 0
    try:
        for run_id in run_ids:
            keys = await _find_document_ids(client, run_id)
            if not keys:
                continue
            documents = []
            for key in keys:
                documents.append({"id": key})
            outcomes = await client.delete_documents(documents=documents)
            for outcome in outcomes:
                if not outcome.succeeded:
                    raise RuntimeError(f"Azure Search did not delete a document of run {run_id}")
            deleted += len(keys)
    finally:
        await client.close()
    return deleted
