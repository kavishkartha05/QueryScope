import logging

from azure.core.credentials import AzureKeyCredential
from azure.search.documents.indexes import SearchIndexClient as SyncSearchIndexClient
from azure.search.documents.indexes.aio import SearchIndexClient as AsyncSearchIndexClient
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.settings import Settings as LlamaSettings
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.vector_stores.azureaisearch import AzureAISearchVectorStore, IndexManagement
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a performance engineer analyzing API benchmark results.
You will be given two sources of context:
  1. Recent runs — the 5 most recent completed benchmark runs from the database.
  2. Semantically similar runs — runs retrieved from a vector search index that \
are most relevant to the question.
Use ONLY the provided context to answer the question — do not invent data.
If the context is insufficient, say so clearly.
Return a concise root cause diagnosis (3–5 sentences maximum).
"""

_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", _SYSTEM_PROMPT),
        (
            "human",
            "Recent runs (latest 5 from Postgres):\n{recent_context}"
            "\n\n---\n\n"
            "Semantically similar runs (from vector search):\n{semantic_context}"
            "\n\nQuestion: {question}",
        ),
    ]
)


async def _fetch_recent_runs_context(db: AsyncSession) -> str:
    """
    Query the 5 most recent completed runs with their metrics from Postgres
    and format them as a human-readable block for the LLM prompt.
    """
    # Import here to avoid circular imports at module load time.
    from app.models.run import Metrics, Run, RunStatus

    result = await db.execute(
        select(Run)
        .where(Run.status == RunStatus.done)
        .order_by(Run.created_at.desc())
        .limit(5)
    )
    # unique() required because selectin-loaded relationships cause duplicate rows.
    runs = result.scalars().unique().all()

    if not runs:
        return "(No completed runs found in the database.)"

    lines: list[str] = []
    for run in runs:
        m = run.metrics[0] if run.metrics else None
        metrics_str = (
            f"p50={m.p50:.1f}ms  p95={m.p95:.1f}ms  p99={m.p99:.1f}ms  "
            f"throughput={m.throughput:.2f}req/s  error_rate={m.error_rate:.2%}"
            if m
            else "metrics not available"
        )
        lines.append(
            f"run_id={run.id}  url={run.target_url}  method={run.method}  "
            f"requests={run.num_requests}  concurrency={run.concurrency}  "
            f"created_at={run.created_at.isoformat()}  {metrics_str}"
        )

    return "\n".join(lines)


async def diagnose(question: str, db: AsyncSession | None = None) -> str:
    """
    Produce a root cause diagnosis for the given question.

    If *db* is provided, the 5 most recent completed runs are fetched from
    Postgres and injected as "Recent runs" context alongside the semantically
    similar runs retrieved from Azure AI Search.
    """
    credential = AzureKeyCredential(settings.azure_search_key)

    # Mirror the same dual-client setup used in indexer.py — the vector store
    # requires both sync (index management) and async (query) clients.
    sync_client = SyncSearchIndexClient(
        endpoint=settings.azure_search_endpoint,
        credential=credential,
    )
    async_client = AsyncSearchIndexClient(
        endpoint=settings.azure_search_endpoint,
        credential=credential,
    )

    try:
        # Use the same embedding model that was used at index time so query
        # vectors are in the same space as document vectors.
        LlamaSettings.embed_model = OpenAIEmbedding(
            model="text-embedding-3-small",
            api_key=settings.openai_api_key,
        )

        vector_store = AzureAISearchVectorStore(
            search_or_index_client=sync_client,
            async_search_or_index_client=async_client,
            index_name=settings.azure_search_index,
            index_management=IndexManagement.VALIDATE_INDEX,
            id_field_key="id",
            chunk_field_key="content",
            embedding_field_key="content_vector",
            metadata_string_field_key="metadata",
            doc_id_field_key="doc_id",
        )

        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex.from_vector_store(
            vector_store=vector_store,
            storage_context=storage_context,
        )

        # similarity_top_k=5 retrieves the 5 most relevant run summaries.
        # More context improves diagnosis quality; 5 keeps the prompt compact.
        retriever = index.as_retriever(similarity_top_k=5)

        logger.info("Retrieving semantic context for question: %s", question)
        nodes = retriever.retrieve(question)
        semantic_context = "\n\n".join(node.get_content() for node in nodes)
        logger.info("Retrieved %d nodes from vector search", len(nodes))

        # Fetch recent runs from Postgres when a session is available.
        if db is not None:
            logger.info("Fetching recent runs from Postgres for RCA context")
            recent_context = await _fetch_recent_runs_context(db)
        else:
            recent_context = "(Database session not provided — recent runs unavailable.)"

        # LCEL chain: inject both context sources + question → prompt → LLM → string.
        # RunnablePassthrough pipes the inputs dict straight into the prompt;
        # retrieval already ran above (LlamaIndex for vectors, SQLAlchemy for recents).
        llm = ChatOpenAI(
            model="gpt-4o-mini",
            api_key=settings.openai_api_key,  # type: ignore[arg-type]
            temperature=0,  # deterministic output for diagnostic text
        )

        chain = (
            RunnablePassthrough()
            | _PROMPT
            | llm
            | StrOutputParser()
        )

        diagnosis: str = await chain.ainvoke(
            {
                "recent_context": recent_context,
                "semantic_context": semantic_context,
                "question": question,
            }
        )
        logger.info("RCA chain completed for question: %s", question)
        return diagnosis

    finally:
        await async_client.close()
        sync_client.close()
