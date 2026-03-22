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

from app.core.config import settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a performance engineer analyzing API benchmark results.
You will be given context extracted from historical benchmark runs.
Use ONLY the provided context to answer the question — do not invent data.
If the context is insufficient, say so clearly.
Return a concise root cause diagnosis (3–5 sentences maximum).
"""

_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", _SYSTEM_PROMPT),
        (
            "human",
            "Context from benchmark runs:\n{context}\n\nQuestion: {question}",
        ),
    ]
)


async def diagnose(question: str) -> str:
    """
    Retrieve relevant benchmark run summaries from Azure AI Search and run
    them through a LangChain LCEL chain to produce a root cause diagnosis.
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

        logger.info("Retrieving context for question: %s", question)
        nodes = retriever.retrieve(question)
        context = "\n\n".join(node.get_content() for node in nodes)
        logger.info("Retrieved %d nodes for RCA", len(nodes))

        # LCEL chain: inject pre-retrieved context + question → prompt → LLM → string.
        # RunnablePassthrough pipes the inputs dict straight into the prompt;
        # we don't use a LangChain retriever here because retrieval already ran
        # above via LlamaIndex (Azure AI Search vector query).
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
            {"context": context, "question": question}
        )
        logger.info("RCA chain completed for question: %s", question)
        return diagnosis

    finally:
        await async_client.close()
        sync_client.close()
