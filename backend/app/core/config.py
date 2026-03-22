from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/queryscope"

    # App
    app_name: str = "QueryScope"
    debug: bool = False

    # Azure AI Search
    azure_search_endpoint: str = ""
    azure_search_key: str = ""
    azure_search_index: str = "benchmark-runs"

    # OpenAI
    openai_api_key: str = ""


# Single instance imported everywhere
settings = Settings()
