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
    doc = Document(
        text=summary,
        metadata={"run_id": str(run_id)},
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
        # (see CLAUDE.md — no alternatives). IndexManagement.VALIDATE_INDEX
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
        )

        logger.info("Indexing run %s to Azure AI Search", run_id)

        # from_documents embeds the document and upserts it into the vector store
        # in one call. We don't need a persistent StorageContext on disk because
        # Azure AI Search is the durable store.
        # afrom_documents does not exist in llama-index-core 0.14.x — sync only.
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
