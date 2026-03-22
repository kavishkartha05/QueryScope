"""
Standalone script to create the Azure AI Search index for QueryScope.

Run from the backend/ directory (so pydantic-settings can find .env):

    poetry run python scripts/create_azure_index.py

The index is idempotent: re-running against an existing index is safe because
create_or_update_index upserts the definition rather than failing on conflict.
"""
import sys

from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import AzureError
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SearchableField,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)

# sys.path adjustment is not needed when run via `poetry run` from backend/,
# but kept as a safety net for direct `python` invocations.
sys.path.insert(0, ".")

from app.core.config import settings  # noqa: E402  (import after sys.path tweak)


def main() -> None:
    client = SearchIndexClient(
        endpoint=settings.azure_search_endpoint,
        credential=AzureKeyCredential(settings.azure_search_key),
    )

    fields = [
        SimpleField(
            name="id",
            type=SearchFieldDataType.String,
            key=True,
        ),
        SearchableField(
            name="content",
            type=SearchFieldDataType.String,
        ),
        # 1536 dimensions matches text-embedding-3-small output.
        # vector_search_profile_name links this field to the HNSW config below.
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=1536,
            vector_search_profile_name="hnsw-profile",
        ),
        SimpleField(
            name="metadata",
            type=SearchFieldDataType.String,
            retrievable=True,
        ),
        SimpleField(
            name="doc_id",
            type=SearchFieldDataType.String,
            retrievable=True,
            filterable=True,
        ),
    ]

    # HNSW (Hierarchical Navigable Small World) is Azure AI Search's default
    # ANN algorithm — good recall/latency trade-off for our embedding size.
    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="hnsw-config")],
        profiles=[
            VectorSearchProfile(
                name="hnsw-profile",
                algorithm_configuration_name="hnsw-config",
            )
        ],
    )

    index = SearchIndex(
        name=settings.azure_search_index,
        fields=fields,
        vector_search=vector_search,
    )

    try:
        client.create_or_update_index(index)
        print(f"Index '{settings.azure_search_index}' created successfully.")
    except AzureError as exc:
        print(f"Failed to create index: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
