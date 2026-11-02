from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/queryscope"

    # App
    app_name: str = "QueryScope"
    debug: bool = False
    cors_origins: list[str] = ["http://localhost:5173"]

    # Azure AI Search
    azure_search_endpoint: str = ""
    azure_search_key: str = ""
    azure_search_index: str = "benchmark-runs"

    # OpenAI
    openai_api_key: str = ""

    # --- Access control -----------------------------------------------------
    # Fail closed: auth is ON unless a local developer explicitly turns it off
    # (AUTH_ENABLED=false). When off, every caller is treated as an admin that
    # owns the shared demo scope, which keeps the local CLI/compose flow working.
    auth_enabled: bool = True
    # Signs session tokens. Required (min 32 chars) when auth is enabled.
    session_secret: str = ""
    # Keyed-hash pepper for access codes. Kept separate from session_secret so
    # rotating session tokens does not invalidate every stored code hash.
    code_pepper: str = ""
    # Shared secret for /admin/* and DELETE /benchmark/runs. Empty = admin routes
    # are disabled (they return 403), never open.
    admin_api_key: str = ""
    token_ttl_hours: int = 12
    # Login throttling (in-memory, so only correct with a single replica).
    login_max_failures_per_ip: int = 5
    login_max_failures_global: int = 100
    login_window_seconds: int = 900
    # Number of trusted reverse-proxy hops in front of the app. 0 = use the
    # socket peer address. With N > 0 the client IP is the Nth entry from the
    # right of X-Forwarded-For (entries to the left are client-controlled).
    trusted_proxy_hops: int = 0


# Single instance imported everywhere
settings = Settings()
