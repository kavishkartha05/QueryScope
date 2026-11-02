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

    # --- Guardrails (hosted demo) --------------------------------------------
    # Hard caps, enforced server-side in the request schemas. They apply even
    # when auth is off; raise them in .env for local load testing.
    max_num_requests: int = 500
    max_concurrency: int = 20
    max_request_timeout_s: float = 10.0
    # Wall-clock limit for one whole run (asyncio.wait_for around the engine).
    run_wall_clock_limit_s: float = 60.0
    # Quotas, computed from the runs table so they survive restarts. Enforced
    # only when auth is enabled (see quotas_enforced): locally there is no code
    # to attribute usage to and the limits would only get in the way.
    max_concurrent_runs: int = 2
    max_active_runs_per_code: int = 1
    # Daily budgets are sums of num_requests per UTC day.
    daily_budget_per_code: int = 2_000
    daily_budget_global: int = 10_000
    # Stale-run reaper: a run still pending/running after the wall-clock limit
    # plus this grace period is marked failed (its worker died or was restarted).
    reaper_grace_seconds: float = 120.0
    reaper_interval_seconds: float = 60.0

    # SSRF: refuse targets that are, or resolve to, non-public addresses.
    # Fail closed: keep this true on any hosted deployment. Set it to false only
    # for local development against localhost services.
    block_private_targets: bool = True
    dns_resolve_timeout_s: float = 5.0
    # Target allowlist: exact hostnames only (no wildcards, no suffix matching),
    # comma-separated. A plain string, not list[str], so ALLOWED_TARGET_HOSTS can
    # be written as a comma-separated value instead of JSON. SSRF checks still
    # apply to allowlisted hosts. Enforcement defaults to ON when auth is on;
    # TARGET_ALLOWLIST_ENABLED overrides it either way.
    allowed_target_hosts: str = "httpbin.org"
    target_allowlist_enabled: bool | None = None
    # Full URL of our own demo target (for example https://demo.example.com/work).
    # Only used by GET /config so the UI can offer it; its host must also be in
    # ALLOWED_TARGET_HOSTS to be accepted by the allowlist.
    demo_target_url: str = ""
    # LLM benchmark route. Defaults to OFF when auth is on (it forwards a
    # caller-supplied API key to a caller-supplied endpoint); LLM_BENCHMARK_ENABLED
    # overrides it either way.
    llm_benchmark_enabled: bool | None = None

    # /health database probe timeout.
    health_db_timeout_s: float = 3.0

    # Each flag below is resolved at call time (not import time) so tests and
    # operators see the current auth_enabled value.
    @property
    def allowlist_enforced(self) -> bool:
        if self.target_allowlist_enabled is not None:
            return self.target_allowlist_enabled
        return self.auth_enabled

    @property
    def quotas_enforced(self) -> bool:
        return self.auth_enabled

    @property
    def llm_benchmark_active(self) -> bool:
        if self.llm_benchmark_enabled is not None:
            return self.llm_benchmark_enabled
        return not self.auth_enabled

    @property
    def allowed_target_host_list(self) -> list[str]:
        """Normalised allowlist entries: lowercase, no trailing dot, no blanks."""
        hosts: list[str] = []
        for raw in self.allowed_target_hosts.split(","):
            entry = raw.strip().lower().rstrip(".")
            if entry:
                hosts.append(entry)
        return hosts


# Single instance imported everywhere
settings = Settings()
