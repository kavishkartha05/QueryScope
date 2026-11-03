import pathlib

BACKEND = pathlib.Path(__file__).resolve().parent.parent


def test_index_name_comes_only_from_config():
    """
    Production uses its own Azure index (AZURE_SEARCH_INDEX), so local development
    documents never reach it. That only holds if no code hard-codes an index name:
    the single literal allowed is the default value in app/core/config.py.
    """
    offenders = []
    for folder in ("app", "scripts"):
        for path in sorted((BACKEND / folder).rglob("*.py")):
            if "benchmark-runs" in path.read_text():
                offenders.append(str(path.relative_to(BACKEND)))
    assert offenders == ["app/core/config.py"]


def test_every_index_client_reads_the_configured_name():
    for relative in ("app/services/indexer.py", "app/services/rca.py", "scripts/create_azure_index.py"):
        source = (BACKEND / relative).read_text()
        assert "settings.azure_search_index" in source, relative
